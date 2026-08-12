"""Report agent: build the structured client-facing report for the UI."""

from __future__ import annotations

from typing import Any

from api.schemas import ClientReport, GraphState


def report_agent(state: GraphState) -> dict[str, Any]:
    """
    Final pipeline step — no LLM required.

    Reuses PR title/body and earlier stage outputs to produce a ClientReport.
    """
    last_test = state.test_results[-1] if state.test_results else None
    tests_passed = bool(last_test and last_test.passed)
    needs_review = state.needs_manual_review or (not tests_passed)

    if tests_passed and state.pr_result and state.pr_result.status == "created":
        status_message = "Fix verified in sandbox and pull request created."
    elif tests_passed and state.pr_result and state.pr_result.status == "pending_approval":
        status_message = (
            "Fix verified in sandbox. Awaiting approval to create the pull request."
        )
    elif tests_passed:
        status_message = "Fix verified in sandbox, but PR creation did not complete."
    else:
        status_message = (
            "Could not automatically confirm the fix — manual review required. "
            "A candidate patch is included below."
        )

    summary_parts = [
        f"{state.bug_report.error_type or 'Error'}: "
        f"{state.bug_report.error_message or 'see traceback'}",
    ]
    if state.code_location:
        summary_parts.append(
            f"at {state.code_location.file_path}:{state.code_location.line_number}"
        )
    if state.root_cause:
        summary_parts.append(f"Cause: {state.root_cause.hypothesis}")

    report = ClientReport(
        summary=" | ".join(summary_parts),
        error_type=state.bug_report.error_type,
        error_message=state.bug_report.error_message,
        file_path=state.code_location.file_path if state.code_location else None,
        line_number=state.code_location.line_number if state.code_location else None,
        root_cause=state.root_cause.hypothesis if state.root_cause else None,
        fix_explanation=state.proposed_fix.explanation if state.proposed_fix else None,
        original_code=state.proposed_fix.original_code if state.proposed_fix else None,
        fixed_code=state.proposed_fix.fixed_code if state.proposed_fix else None,
        files=list(state.proposed_fix.files) if state.proposed_fix else [],
        tests_passed=tests_passed,
        attempts=len(state.test_results),
        pr_url=state.pr_result.pr_url if state.pr_result else None,
        needs_manual_review=needs_review,
        status_message=status_message,
        pr_title=state.pr_title,
        pr_body=state.pr_body,
    )

    return {
        "client_report": report,
        "needs_manual_review": needs_review,
        "current_stage": "report",
    }
