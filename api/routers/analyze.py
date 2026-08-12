"""Analyze endpoints: start pipeline, poll status, fetch result, approve PR."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from api.agents.pr_writer_agent import publish_fix_as_pr
from api.api_schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeResultResponse,
    AnalyzeStatusResponse,
    ApproveResponse,
)
from api.runner import execute_analysis
from api.store import run_store

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("", response_model=AnalyzeResponse)
async def start_analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    run = run_store.create(traceback=body.traceback, max_retries=body.max_retries)
    asyncio.create_task(asyncio.to_thread(execute_analysis, run.run_id))
    return AnalyzeResponse(run_id=run.run_id, status=run.status)


@router.get("/{run_id}/status", response_model=AnalyzeStatusResponse)
async def get_status(run_id: str) -> AnalyzeStatusResponse:
    run = run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")

    state = run.state
    return AnalyzeStatusResponse(
        run_id=run.run_id,
        status=run.status,
        current_stage=state.current_stage if state else None,
        stages_completed=list(run.stages_completed),
        retry_count=state.retry_count if state else 0,
        max_retries=state.max_retries if state else 3,
        needs_manual_review=bool(state and state.needs_manual_review),
        error=run.error,
        updated_at=run.updated_at,
    )


@router.get("/{run_id}/result", response_model=AnalyzeResultResponse)
async def get_result(run_id: str) -> AnalyzeResultResponse:
    run = run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")

    state = run.state
    diff = None
    if state and state.proposed_fix:
        fix = state.proposed_fix
        files = [
            {
                "file_path": p.file_path,
                "original_code": p.original_code,
                "fixed_code": p.fixed_code or p.content,
                "content": p.content or p.fixed_code,
            }
            for p in fix.files
        ]
        first = files[0] if files else {}
        diff = {
            "file_path": first.get("file_path") or fix.file_path,
            "original_code": first.get("original_code") or fix.original_code,
            "fixed_code": first.get("fixed_code") or fix.fixed_code,
            "explanation": fix.explanation,
            "files": files,
        }

    return AnalyzeResultResponse(
        run_id=run.run_id,
        status=run.status,
        stages_completed=list(run.stages_completed),
        state=state,
        report=state.client_report if state else None,
        pr_result=state.pr_result if state else None,
        diff=diff,
        error=run.error,
    )


@router.post("/{run_id}/approve", response_model=ApproveResponse)
async def approve_pr(run_id: str) -> ApproveResponse:
    run = run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    if run.status != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Run is '{run.status}', expected 'awaiting_approval'",
        )
    if run.state is None:
        raise HTTPException(status_code=400, detail="Run has no state")

    last = run.state.test_results[-1] if run.state.test_results else None
    if not last or not last.passed:
        raise HTTPException(
            status_code=400,
            detail="Cannot approve PR — sandbox tests did not pass",
        )

    try:
        pr_result = await asyncio.to_thread(publish_fix_as_pr, run.state)
    except Exception as exc:
        run_store.update(run_id, status="failed", error=str(exc))
        return ApproveResponse(
            run_id=run_id,
            status="failed",
            pr_result=None,
            message=f"PR creation failed: {exc}",
        )

    new_state = run.state.model_copy(update={"pr_result": pr_result})
    if new_state.client_report is not None:
        new_state = new_state.model_copy(
            update={
                "client_report": new_state.client_report.model_copy(
                    update={
                        "pr_url": pr_result.pr_url,
                        "needs_manual_review": False,
                        "status_message": "Fix verified and pull request created.",
                    }
                )
            }
        )
    run_store.update(run_id, status="done", state=new_state, stage="approve")
    return ApproveResponse(
        run_id=run_id,
        status="done",
        pr_result=pr_result,
        message="Pull request created",
    )
