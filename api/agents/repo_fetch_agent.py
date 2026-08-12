"""Repo fetch agent: clone the target GitHub repo into a per-run temp directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from git import Repo

from api.config import get_settings
from api.schemas import GraphState


def repo_fetch_agent(state: GraphState) -> dict[str, Any]:
    """
    Clone GITHUB_REPO_* into /tmp/runs/{run_id}/repo.

    Pure git operation — no LLM. Must run after triage and before locator.
    """
    settings = get_settings()
    run_id = state.run_id or "anonymous"
    dest = Path(settings.runs_root) / run_id / "repo"

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    Repo.clone_from(
        settings.github_clone_url,
        str(dest),
        depth=1,
        single_branch=True,
    )

    return {
        "repo_path": str(dest),
        "current_stage": "repo_fetch",
    }


def cleanup_repo(repo_path: str | None) -> None:
    """Remove a per-run clone directory (call after the graph finishes)."""
    if not repo_path:
        return
    path = Path(repo_path)
    # Remove the run directory (/tmp/runs/{run_id}) if structure matches
    run_dir = path.parent if path.name == "repo" else path
    shutil.rmtree(run_dir, ignore_errors=True)
