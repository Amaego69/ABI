"""PR writer agent: draft PR title/body; publishing happens on explicit approve."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from api.agents.llm import call_structured
from api.publishers import PRPublisher, get_publisher
from api.schemas import FilePatch, GraphState, PRResult


class PRDraft(BaseModel):
    title: str = Field(description="Concise PR title")
    body: str = Field(description="Markdown PR body")


def _patches(state: GraphState) -> list[FilePatch]:
    fix = state.proposed_fix
    if not fix:
        return []
    if fix.files:
        return list(fix.files)
    if fix.file_path and fix.fixed_code is not None:
        return [
            FilePatch(
                file_path=fix.file_path,
                content=fix.fixed_code,
                original_code=fix.original_code or "",
                fixed_code=fix.fixed_code,
            )
        ]
    return []


def _format_patch_markdown(patches: list[FilePatch]) -> str:
    chunks: list[str] = []
    for patch in patches:
        before = patch.original_code or "(previous content)"
        after = patch.content or patch.fixed_code
        # Keep PR bodies readable for small files; truncate huge ones
        if len(before) > 2500:
            before = before[:2500] + "\n# ... truncated ..."
        if len(after) > 2500:
            after = after[:2500] + "\n# ... truncated ..."
        chunks.append(
            f"### `{patch.file_path}`\n\n"
            f"**Before**\n```python\n{before}\n```\n\n"
            f"**After**\n```python\n{after}\n```"
        )
    return "\n\n".join(chunks)


def branch_name_for(state: GraphState) -> str:
    err = (state.bug_report.error_type or "bug").lower()
    err = re.sub(r"[^a-z0-9]+", "-", err).strip("-")[:24] or "bug"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run = (state.run_id or "run")[:8]
    return f"fix/{err}-{run}-{stamp}"


def _prepare_fixed_files(state: GraphState) -> dict[str, str]:
    """Write full-file fixes onto the clone and return {path: content}."""
    patches = _patches(state)
    if not patches:
        return {}

    contents = {
        p.file_path: (p.content or p.fixed_code)
        for p in patches
        if (p.content or p.fixed_code)
    }
    if not state.repo_path:
        return contents

    from api.agents.sandbox_test_agent import _apply_fix
    from git import Repo as GitRepo

    repo = Path(state.repo_path)
    paths = list(contents)
    try:
        GitRepo(str(repo)).git.checkout("--", *paths)
    except Exception:
        pass

    for path, body in contents.items():
        try:
            _apply_fix(repo, path, body)
        except Exception:
            pass
    return contents


def pr_writer_agent(state: GraphState) -> dict[str, Any]:
    """
    Generate a human-readable PR description.

    Does not open a GitHub PR — that happens via POST /api/analyze/{run_id}/approve
    after human confirmation (or publish_fix_as_pr for auto mode).
    """
    last_test = state.test_results[-1] if state.test_results else None
    tests_passed = bool(last_test and last_test.passed)

    loc = state.code_location
    fix = state.proposed_fix
    cause = state.root_cause
    patches = _patches(state)
    files_label = ", ".join(p.file_path for p in patches) or (
        loc.file_path if loc else "unknown"
    )

    user_prompt = (
        f"Error: {state.bug_report.error_type}: {state.bug_report.error_message}\n"
        f"Primary location: {loc.file_path if loc else 'unknown'}:"
        f"{loc.line_number if loc else 'unknown'}\n"
        f"Files changed: {files_label}\n"
        f"Root cause: {cause.hypothesis if cause else 'n/a'}\n"
        f"Fix explanation: {fix.explanation if fix else 'n/a'}\n\n"
        f"{_format_patch_markdown(patches)}\n\n"
        f"Sandbox passed: {tests_passed}\n"
        f"Attempts: {len(state.test_results)}\n"
        f"Last sandbox output (truncated):\n{(last_test.output if last_test else '')[:1500]}"
    )

    try:
        draft = call_structured(
            system=(
                "You write clear GitHub pull request descriptions for automated bug fixes. "
                "Title should be imperative and specific. Body must cover: what broke "
                "(files, line, reason), what changed across all touched files, and how it "
                "was verified (sandbox result)."
            ),
            user=user_prompt,
            schema=PRDraft,
            trace_name="pr_writer_agent",
        )
    except Exception:
        draft = PRDraft(
            title=f"Fix {state.bug_report.error_type or 'bug'} in {files_label}",
            body=(
                f"## Summary\n"
                f"- Error: `{state.bug_report.error_type}: {state.bug_report.error_message}`\n"
                f"- Location: `{loc.file_path if loc else 'unknown'}:"
                f"{loc.line_number if loc else '?'}`\n"
                f"- Cause: {cause.hypothesis if cause else 'n/a'}\n\n"
                f"## Fix\n{fix.explanation if fix else 'n/a'}\n\n"
                f"{_format_patch_markdown(patches)}\n\n"
                f"## Verification\n"
                f"Sandbox passed: **{tests_passed}** "
                f"(attempts: {len(state.test_results)})\n"
            ),
        )

    branch = branch_name_for(state)
    fixed_files = _prepare_fixed_files(state) if tests_passed else {}

    updates: dict[str, Any] = {
        "pr_title": draft.title,
        "pr_body": draft.body,
        "current_stage": "pr_writer",
        "extra": {
            **(state.extra or {}),
            "fixed_files": fixed_files,
            "fixed_file_content": next(iter(fixed_files.values()), ""),
        },
    }

    if not tests_passed:
        updates["needs_manual_review"] = True
        updates["pr_result"] = PRResult(branch_name=branch, status="failed")
        return updates

    updates["pr_result"] = PRResult(
        branch_name=branch,
        status="pending_approval",
    )
    return updates


def publish_fix_as_pr(
    state: GraphState,
    publisher: PRPublisher | None = None,
) -> PRResult:
    """
    Push the proposed fix and open a PR via PRPublisher.

    Used by the approve endpoint after human-in-the-loop confirmation.
    """
    if state.proposed_fix is None:
        raise ValueError("No proposed_fix to publish")
    if not state.pr_title or not state.pr_body:
        raise ValueError("PR title/body missing — run pr_writer first")

    branch = (
        state.pr_result.branch_name
        if state.pr_result and state.pr_result.branch_name
        else branch_name_for(state)
    )
    files = (state.extra or {}).get("fixed_files") or _prepare_fixed_files(state)
    if not files:
        raise ValueError("Fixed file contents are empty")

    pub = publisher or get_publisher()
    pub.create_branch(base="main", branch_name=branch)
    if hasattr(pub, "commit_and_push_files"):
        pub.commit_and_push_files(
            branch_name=branch,
            files=files,
            message=state.pr_title,
        )
    else:
        for path, content in files.items():
            pub.commit_and_push(
                branch_name=branch,
                file_path=path,
                content=content,
                message=state.pr_title,
            )
    return pub.open_pr(branch_name=branch, title=state.pr_title, body=state.pr_body)
