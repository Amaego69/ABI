"""LangGraph pipeline: triage → … → sandbox_test (retry) → pr_writer → report."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from api.agents import (
    cleanup_repo,
    fix_generator_agent,
    locator_agent,
    pr_writer_agent,
    repo_fetch_agent,
    report_agent,
    root_cause_agent,
    sandbox_test_agent,
    triage_agent,
)
from api.observability import traced_callable
from api.schemas import BugReport, GraphState


def route_after_sandbox(
    state: GraphState,
) -> Literal["fix_generator", "pr_writer"]:
    """
    Retry fix generation while sandbox fails and attempts remain.

    Otherwise continue to pr_writer (which skips opening a PR when tests failed).
    """
    last = state.test_results[-1] if state.test_results else None
    if last is not None and last.passed:
        return "pr_writer"
    # Empty patch means generator already failed — don't burn retries in sandbox
    fix = state.proposed_fix
    if fix is not None and not fix.files and not (fix.file_path and fix.fixed_code):
        return "pr_writer"
    if state.retry_count < state.max_retries:
        return "fix_generator"
    return "pr_writer"


def build_graph() -> StateGraph:
    """Assemble the investigation StateGraph (uncompiled)."""
    graph = StateGraph(GraphState)

    # Each node is wrapped as a Langfuse agent span (no-op when Langfuse is off)
    graph.add_node("triage", traced_callable("triage", as_type="agent")(triage_agent))
    graph.add_node(
        "repo_fetch", traced_callable("repo_fetch", as_type="tool")(repo_fetch_agent)
    )
    graph.add_node("locator", traced_callable("locator", as_type="agent")(locator_agent))
    graph.add_node(
        "root_cause", traced_callable("root_cause", as_type="agent")(root_cause_agent)
    )
    graph.add_node(
        "fix_generator",
        traced_callable("fix_generator", as_type="agent")(fix_generator_agent),
    )
    graph.add_node(
        "sandbox_test",
        traced_callable("sandbox_test", as_type="tool")(sandbox_test_agent),
    )
    graph.add_node(
        "pr_writer", traced_callable("pr_writer", as_type="agent")(pr_writer_agent)
    )
    graph.add_node("report", traced_callable("report", as_type="span")(report_agent))

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "repo_fetch")
    graph.add_edge("repo_fetch", "locator")
    graph.add_edge("locator", "root_cause")
    graph.add_edge("root_cause", "fix_generator")
    graph.add_edge("fix_generator", "sandbox_test")
    graph.add_conditional_edges(
        "sandbox_test",
        route_after_sandbox,
        {
            "fix_generator": "fix_generator",
            "pr_writer": "pr_writer",
        },
    )
    graph.add_edge("pr_writer", "report")
    graph.add_edge("report", END)

    return graph


def compile_graph():
    """Return a compiled LangGraph runnable."""
    return build_graph().compile()


def initial_state(
    traceback: str,
    *,
    run_id: str | None = None,
    max_retries: int = 3,
) -> GraphState:
    """Build the starting GraphState for a new analysis run."""
    return GraphState(
        bug_report=BugReport(
            raw_traceback=traceback,
            triggered_at=datetime.now(timezone.utc),
        ),
        run_id=run_id or uuid.uuid4().hex,
        max_retries=max_retries,
        current_stage="pending",
    )


def run_investigation(
    traceback: str,
    *,
    run_id: str | None = None,
    max_retries: int = 3,
    cleanup: bool = True,
) -> GraphState:
    """
    Execute the full graph synchronously and return the final state.

    Always attempts to delete the per-run clone directory when `cleanup` is True.
    """
    from pathlib import Path

    from api.config import get_settings

    state = initial_state(traceback, run_id=run_id, max_retries=max_retries)
    app = compile_graph()
    final: GraphState | dict[str, Any] | None = None
    try:
        final = app.invoke(state)
        if isinstance(final, dict):
            final = GraphState.model_validate(final)
        return final
    finally:
        if cleanup:
            repo_path = None
            if isinstance(final, GraphState):
                repo_path = final.repo_path
            elif isinstance(final, dict):
                repo_path = final.get("repo_path")
            if not repo_path and state.run_id:
                repo_path = str(
                    Path(get_settings().runs_root) / state.run_id / "repo"
                )
            cleanup_repo(repo_path)
