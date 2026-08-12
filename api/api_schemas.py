"""HTTP request/response models for the FastAPI layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from api.schemas import ClientReport, GraphState, PRResult


class AnalyzeRequest(BaseModel):
    traceback: str = Field(min_length=1, description="Raw Python traceback text")
    max_retries: int = Field(default=3, ge=1, le=5)


class AnalyzeResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "awaiting_approval", "done", "failed"]


class AnalyzeStatusResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "awaiting_approval", "done", "failed"]
    current_stage: str | None = None
    stages_completed: list[str] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    needs_manual_review: bool = False
    error: str | None = None
    updated_at: datetime | None = None


class AnalyzeResultResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "awaiting_approval", "done", "failed"]
    stages_completed: list[str] = Field(default_factory=list)
    state: GraphState | None = None
    report: ClientReport | None = None
    pr_result: PRResult | None = None
    diff: dict[str, Any] | None = None
    error: str | None = None


class ApproveResponse(BaseModel):
    run_id: str
    status: Literal["done", "failed", "awaiting_approval"]
    pr_result: PRResult | None = None
    message: str = ""


class BuggyTriggerResponse(BaseModel):
    bug_id: str
    upstream_status: int
    detail: Any = None
    note: str | None = None
