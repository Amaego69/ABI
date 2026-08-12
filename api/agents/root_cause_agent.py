"""Root-cause agent: hypothesize why the bug occurs (LLM, Chain-of-Thought)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from api.agents.llm import call_structured
from api.schemas import GraphState, RootCauseAnalysis


class RootCauseLLMResult(BaseModel):
    reasoning: str = Field(description="Step-by-step chain-of-thought analysis")
    hypothesis: str = Field(description="Concise root-cause hypothesis (required)")
    confidence: Literal["low", "medium", "high"]

    @model_validator(mode="before")
    @classmethod
    def _coerce_aliases(cls, data: Any) -> Any:
        """
        Models sometimes put the whole answer in `reasoning` and omit `hypothesis`,
        or use synonyms. Recover so structured output does not hard-fail.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get("hypothesis"):
            for key in ("root_cause", "cause", "conclusion", "summary"):
                val = out.get(key)
                if isinstance(val, str) and val.strip():
                    out["hypothesis"] = val.strip()
                    break
            else:
                reasoning = out.get("reasoning")
                if isinstance(reasoning, str) and reasoning.strip():
                    out["hypothesis"] = reasoning.strip()
        if not out.get("reasoning") and out.get("hypothesis"):
            out["reasoning"] = out["hypothesis"]
        return out


def root_cause_agent(state: GraphState) -> dict[str, Any]:
    """Formulate a root-cause hypothesis from CodeLocation + BugReport."""
    if state.code_location is None:
        raise RuntimeError("code_location is missing — run locator_agent first")

    loc = state.code_location
    report = state.bug_report

    try:
        result = call_structured(
            system=(
                "You are a senior Python debugger. Think step-by-step about why the "
                "observed exception occurs in the given code. Be specific about the "
                "faulty assumption (e.g. empty list, wrong type, missing await).\n"
                "When calling emit_result you MUST provide ALL three fields:\n"
                "- reasoning: step-by-step analysis\n"
                "- hypothesis: one concise root-cause sentence\n"
                "- confidence: low | medium | high"
            ),
            user=(
                f"Error type: {report.error_type}\n"
                f"Error message: {report.error_message}\n"
                f"File: {loc.file_path}\n"
                f"Function: {loc.function_name}\n"
                f"Line: {loc.line_number}\n\n"
                f"Surrounding code:\n{loc.surrounding_code}\n\n"
                f"Traceback:\n{report.raw_traceback[:4000]}"
            ),
            schema=RootCauseLLMResult,
            trace_name="root_cause_agent",
        )
        analysis = RootCauseAnalysis(
            hypothesis=result.hypothesis,
            confidence=result.confidence,
        )
        extra = {**(state.extra or {}), "root_cause_reasoning": result.reasoning}
    except Exception as exc:
        # Deterministic fallback so the pipeline can continue offline
        analysis = RootCauseAnalysis(
            hypothesis=(
                f"{report.error_type or 'Error'} at {loc.file_path}:"
                f"{loc.line_number} — {report.error_message or 'see traceback'}. "
                f"Likely missing validation or type coercion. ({exc})"
            ),
            confidence="low",
        )
        extra = {**(state.extra or {}), "root_cause_error": str(exc)}

    return {
        "root_cause": analysis,
        "extra": extra,
        "current_stage": "root_cause",
    }
