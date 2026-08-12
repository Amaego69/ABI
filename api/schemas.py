"""Pydantic schemas for the LangGraph bug-investigation pipeline state."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BugReport(BaseModel):
    raw_traceback: str
    error_type: str | None = None
    error_message: str | None = None
    triggered_at: datetime
    # Filled by triage from the first relevant traceback frame
    file_path: str | None = None
    line_number: int | None = None
    function_name: str | None = None


class CodeLocation(BaseModel):
    file_path: str
    function_name: str | None = None
    line_number: int | None = None
    surrounding_code: str  # ±15 lines of context around the fault


class RootCauseAnalysis(BaseModel):
    hypothesis: str
    confidence: Literal["low", "medium", "high"]


class FilePatch(BaseModel):
    """
    One file change inside a proposed fix.

    Primary field is `content` — the full new file to write on disk.
    `original_code` / `fixed_code` are kept for UI diffs (full before/after).
    """

    file_path: str
    content: str = ""
    original_code: str = ""
    fixed_code: str = ""

    @model_validator(mode="after")
    def _sync_content_aliases(self) -> "FilePatch":
        # Prefer explicit full-file content; fall back to fixed_code
        if self.content and not self.fixed_code:
            self.fixed_code = self.content
        elif self.fixed_code and not self.content:
            self.content = self.fixed_code
        return self


class ProposedFix(BaseModel):
    """
    A complete proposed fix — may rewrite one or many files in a single attempt.

    Each FilePatch carries the full new file contents (written directly to disk).
    Legacy single-file fields are accepted and normalized into `files`.
    """

    files: list[FilePatch] = Field(default_factory=list)
    explanation: str = ""

    # Legacy single-file aliases (optional input / convenience accessors)
    file_path: str | None = None
    original_code: str | None = None
    fixed_code: str | None = None

    @model_validator(mode="after")
    def _normalize_files(self) -> "ProposedFix":
        if not self.files and self.file_path and self.fixed_code is not None:
            self.files = [
                FilePatch(
                    file_path=self.file_path,
                    content=self.fixed_code,
                    original_code=self.original_code or "",
                    fixed_code=self.fixed_code,
                )
            ]
        if self.files and not self.file_path:
            first = self.files[0]
            self.file_path = first.file_path
            self.original_code = first.original_code
            self.fixed_code = first.fixed_code or first.content
        return self

    @property
    def file_paths(self) -> list[str]:
        return [f.file_path for f in self.files]


class TestResult(BaseModel):
    passed: bool
    output: str
    attempt_number: int


class PRResult(BaseModel):
    branch_name: str
    pr_url: str | None = None
    pr_number: int | None = None
    status: Literal["created", "failed", "pending_approval"]


class ClientReport(BaseModel):
    """Structured report shown in the UI after the pipeline finishes."""

    summary: str
    error_type: str | None = None
    error_message: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    root_cause: str | None = None
    fix_explanation: str | None = None
    original_code: str | None = None
    fixed_code: str | None = None
    files: list[FilePatch] = Field(default_factory=list)
    tests_passed: bool | None = None
    attempts: int = 0
    pr_url: str | None = None
    needs_manual_review: bool = False
    status_message: str = ""
    pr_title: str | None = None
    pr_body: str | None = None


class GraphState(BaseModel):
    bug_report: BugReport
    code_location: CodeLocation | None = None
    root_cause: RootCauseAnalysis | None = None
    proposed_fix: ProposedFix | None = None
    test_results: list[TestResult] = Field(default_factory=list)
    pr_result: PRResult | None = None
    retry_count: int = 0
    max_retries: int = 3

    # Runtime fields used by agents (not in the original sketch, required to wire the pipeline)
    run_id: str = ""
    repo_path: str | None = None
    current_stage: str | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    client_report: ClientReport | None = None
    needs_manual_review: bool = False
    triggered_endpoint: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
