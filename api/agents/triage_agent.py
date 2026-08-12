"""Triage agent: parse traceback into structured BugReport fields via LLM (+ regex fallback)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from api.agents.llm import call_structured
from api.schemas import BugReport, CodeLocation, GraphState


class TriageExtraction(BaseModel):
    error_type: str
    error_message: str
    file_path: str | None = None
    line_number: int | None = None
    function_name: str | None = None
    triggered_endpoint: str | None = Field(
        default=None,
        description="HTTP path that triggered the error, if present in the traceback",
    )


_FRAME_RE = re.compile(
    r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?'
)
_EXC_RE = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(.*))?$"
)
_ENDPOINT_RE = re.compile(r"(/trigger/[A-Za-z0-9\-_/]+)")

# When traceback is truncated (only site-packages frames), map known demo routes
_ENDPOINT_LOCATION_HINTS: dict[str, tuple[str, str]] = {
    "/trigger/empty-cart-checkout": ("utils.py", "find_cheapest_item"),
    "/trigger/invalid-discount-type": ("utils.py", "apply_percent_discount"),
    "/trigger/async-price-fetch": ("services.py", "get_async_price_summary"),
}


def _is_stdlib_or_site(path: str) -> bool:
    p = path.replace("\\", "/")
    return (
        "site-packages" in p
        or "/usr/lib/" in p
        or "/usr/local/lib/" in p
        or p.endswith("threading.py")
        or "/concurrent/" in p
    )


def _regex_triage(raw: str) -> TriageExtraction:
    frames = list(_FRAME_RE.finditer(raw))
    # Prefer the last frame that looks like project code (not site-packages / stdlib)
    chosen = None
    for frame in reversed(frames):
        path = frame.group("file")
        if _is_stdlib_or_site(path):
            continue
        chosen = frame
        break
    # NEVER fall back to site-packages — that produces garbage like routing.py:1780

    error_type = "Error"
    error_message = ""
    for line in reversed([ln.strip() for ln in raw.splitlines() if ln.strip()]):
        match = _EXC_RE.match(line)
        if match:
            error_type = match.group(1)
            error_message = match.group(2) or ""
            break
        # Pydantic / FastAPI often surface as "ResponseValidationError: ..."
        if "ValidationError" in line or "ResponseValidationError" in line:
            error_type = "ValidationError"
            error_message = line
            break

    endpoint = None
    ep = _ENDPOINT_RE.search(raw)
    if ep:
        endpoint = ep.group(1).replace("_", "-")
        # normalize underscore mistakes in path
        if endpoint.startswith("/trigger/"):
            endpoint = "/trigger/" + endpoint[len("/trigger/") :].replace("_", "-")

    file_path = chosen.group("file") if chosen else None
    line_number = int(chosen.group("line")) if chosen else None
    function_name = chosen.group("func") if chosen else None

    # Truncated traceback hint: recover demo location from endpoint
    if file_path is None and endpoint:
        hint = _ENDPOINT_LOCATION_HINTS.get(endpoint)
        if hint:
            file_path, function_name = hint

    return TriageExtraction(
        error_type=error_type,
        error_message=error_message,
        file_path=file_path,
        line_number=line_number,
        function_name=function_name,
        triggered_endpoint=endpoint,
    )


def _normalize_repo_relative(path: str | None) -> str | None:
    if not path:
        return None
    normalized = path.replace("\\", "/")
    for marker in ("/buggy-app/", "/repo/", "/app/", "/work/"):
        if marker in normalized:
            return normalized.split(marker, 1)[1]
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        parts = [p for p in normalized.split("/") if p]
        for i, part in enumerate(parts):
            if part.endswith(".py"):
                return "/".join(parts[i:])
        return parts[-1] if parts else None
    return normalized.lstrip("./")


def triage_agent(state: GraphState) -> dict[str, Any]:
    """Extract error type, message, and first relevant file/line from the traceback."""
    raw = state.bug_report.raw_traceback
    fallback = _regex_triage(raw)

    try:
        extraction = call_structured(
            system=(
                "You are a triage agent for a Python bug investigation pipeline. "
                "Given a raw traceback, extract the exception type, message, and the "
                "most relevant application frame (file, line, function). Prefer project "
                "code over site-packages/stdlib. line_number MUST come from a real "
                "'File \"...\", line N' frame — never invent large line numbers. "
                "If an HTTP endpoint like /trigger/... appears, include triggered_endpoint."
            ),
            user=f"Traceback:\n\n{raw[:8000]}",
            schema=TriageExtraction,
            trace_name="triage_agent",
        )
    except Exception:
        extraction = fallback

    # Regex is source of truth for location — LLMs often hallucinate line numbers
    if fallback.file_path:
        extraction.file_path = fallback.file_path
    if fallback.line_number is not None:
        extraction.line_number = fallback.line_number
    if fallback.function_name:
        extraction.function_name = fallback.function_name
    if fallback.triggered_endpoint:
        extraction.triggered_endpoint = fallback.triggered_endpoint
    if fallback.error_type and fallback.error_type != "Error":
        extraction.error_type = fallback.error_type
        if fallback.error_message:
            extraction.error_message = fallback.error_message

    # Sanity: absurd line numbers from LLM noise
    if extraction.line_number is not None and extraction.line_number > 100_000:
        extraction.line_number = fallback.line_number

    rel_path = _normalize_repo_relative(extraction.file_path)

    bug_report = state.bug_report.model_copy(
        update={
            "error_type": extraction.error_type,
            "error_message": extraction.error_message,
            "file_path": rel_path,
            "line_number": extraction.line_number,
            "function_name": extraction.function_name,
        }
    )

    code_location = None
    if rel_path:
        code_location = CodeLocation(
            file_path=rel_path,
            function_name=extraction.function_name,
            line_number=extraction.line_number,
            surrounding_code="",
        )

    return {
        "bug_report": bug_report,
        "code_location": code_location,
        "triggered_endpoint": extraction.triggered_endpoint,
        "current_stage": "triage",
    }
