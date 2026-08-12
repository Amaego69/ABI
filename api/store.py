"""In-memory store for analysis runs (status polling for the frontend)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from api.schemas import GraphState

RunStatus = Literal["pending", "running", "awaiting_approval", "done", "failed"]


@dataclass
class AnalysisRun:
    run_id: str
    status: RunStatus = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state: GraphState | None = None
    error: str | None = None
    stages_completed: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class RunStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, AnalysisRun] = {}

    def create(self, *, traceback: str, max_retries: int = 3) -> AnalysisRun:
        from api.graph import initial_state

        run_id = uuid.uuid4().hex
        state = initial_state(traceback, run_id=run_id, max_retries=max_retries)
        run = AnalysisRun(run_id=run_id, status="pending", state=state)
        with self._lock:
            self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> AnalysisRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def update(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        state: GraphState | dict[str, Any] | None = None,
        error: str | None = None,
        stage: str | None = None,
    ) -> AnalysisRun:
        with self._lock:
            run = self._runs[run_id]
            if status is not None:
                run.status = status
            if state is not None:
                if isinstance(state, dict):
                    run.state = GraphState.model_validate(state)
                else:
                    run.state = state
            if error is not None:
                run.error = error
            if stage and stage not in run.stages_completed:
                run.stages_completed.append(stage)
            run.touch()
            return run


# Process-wide store (swap for Redis/Postgres later)
run_store = RunStore()

# Last error captured when proxying buggy-app trigger endpoints
_latest_buggy_error_lock = threading.Lock()
_latest_buggy_error: dict[str, Any] | None = None


def set_latest_buggy_error(payload: dict[str, Any]) -> None:
    global _latest_buggy_error
    with _latest_buggy_error_lock:
        _latest_buggy_error = {
            **payload,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


def get_latest_buggy_error() -> dict[str, Any] | None:
    with _latest_buggy_error_lock:
        return dict(_latest_buggy_error) if _latest_buggy_error else None
