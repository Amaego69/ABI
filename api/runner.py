"""Background runner that executes the LangGraph pipeline for a run_id."""

from __future__ import annotations

import logging
from pathlib import Path

from api.agents.pr_writer_agent import publish_fix_as_pr
from api.agents.repo_fetch_agent import cleanup_repo
from api.config import get_settings
from api.graph import compile_graph
from api.observability import flush_langfuse, observation
from api.schemas import GraphState
from api.store import run_store

logger = logging.getLogger(__name__)


def _as_state(value: GraphState | dict) -> GraphState:
    if isinstance(value, GraphState):
        return value
    return GraphState.model_validate(value)


def execute_analysis(run_id: str) -> None:
    """
    Run the investigation graph, streaming stage updates into the run store.

    Terminal status:
    - awaiting_approval — sandbox passed, PR draft ready (HITL)
    - done — finished without PR (manual review) or auto-PR created
    - failed — unhandled pipeline exception
    """
    run = run_store.get(run_id)
    if run is None or run.state is None:
        return

    settings = get_settings()
    app = compile_graph()
    run_store.update(run_id, status="running")

    final: GraphState | None = None
    try:
        with observation(
            f"investigation-{run_id}",
            as_type="chain",
            input={
                "run_id": run_id,
                "traceback_preview": (run.state.bug_report.raw_traceback or "")[:1500],
                "max_retries": run.state.max_retries,
            },
            metadata={"run_id": run_id, "pipeline": "bug_investigator"},
        ) as root:
            for event in app.stream(run.state, stream_mode="values"):
                state = _as_state(event)
                stage = state.current_stage
                run_store.update(run_id, state=state, stage=stage)
                final = state

            if final is None:
                run_store.update(run_id, status="failed", error="Graph produced no state")
                if root is not None:
                    root.update(
                        output={"status": "failed", "error": "no state"},
                        level="ERROR",
                    )
                return

            last_test = final.test_results[-1] if final.test_results else None
            tests_passed = bool(last_test and last_test.passed)
            terminal_status = "done"

            if tests_passed and settings.auto_create_pr and not settings.require_pr_approval:
                try:
                    pr_result = publish_fix_as_pr(final)
                    final = final.model_copy(
                        update={
                            "pr_result": pr_result,
                            "client_report": (
                                final.client_report.model_copy(
                                    update={"pr_url": pr_result.pr_url}
                                )
                                if final.client_report
                                else final.client_report
                            ),
                        }
                    )
                    run_store.update(run_id, status="done", state=final, stage="approve")
                    terminal_status = "done"
                except Exception as exc:
                    logger.exception("Auto PR creation failed for %s", run_id)
                    run_store.update(
                        run_id,
                        status="failed",
                        state=final,
                        error=f"Auto PR creation failed: {exc}",
                    )
                    terminal_status = "failed"
            elif tests_passed:
                run_store.update(run_id, status="awaiting_approval", state=final)
                terminal_status = "awaiting_approval"
            else:
                run_store.update(run_id, status="done", state=final)
                terminal_status = "done"

            if root is not None:
                root.update(
                    output={
                        "status": terminal_status,
                        "error_type": final.bug_report.error_type,
                        "retry_count": final.retry_count,
                        "tests_passed": tests_passed,
                        "needs_manual_review": final.needs_manual_review,
                        "stages": [
                            s.current_stage
                            for s in [final]
                            if s.current_stage
                        ],
                        "current_stage": final.current_stage,
                    }
                )
    except Exception as exc:
        logger.exception("Analysis failed for %s", run_id)
        run_store.update(run_id, status="failed", error=str(exc), state=final)
    finally:
        flush_langfuse()
        # Keep fixed_file_content in state.extra; clone can go away
        repo_path = None
        current = run_store.get(run_id)
        if current and current.state:
            repo_path = current.state.repo_path
        if not repo_path:
            repo_path = str(Path(settings.runs_root) / run_id / "repo")
        cleanup_repo(repo_path)
        if current and current.state and current.state.repo_path:
            cleaned = current.state.model_copy(update={"repo_path": None})
            run_store.update(run_id, state=cleaned)
