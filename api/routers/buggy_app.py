"""Proxy helpers for the standalone buggy-app demo service."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from api.api_schemas import BuggyTriggerResponse
from api.config import get_settings
from api.store import get_latest_buggy_error, set_latest_buggy_error

router = APIRouter(prefix="/api/buggy-app", tags=["buggy-app"])

BUG_ENDPOINTS: dict[str, tuple[str, str]] = {
    # bug_id -> (method, path)
    "1": ("POST", "/trigger/empty-cart-checkout"),
    "bug1": ("POST", "/trigger/empty-cart-checkout"),
    "empty-cart-checkout": ("POST", "/trigger/empty-cart-checkout"),
    "2": ("POST", "/trigger/invalid-discount-type"),
    "bug2": ("POST", "/trigger/invalid-discount-type"),
    "invalid-discount-type": ("POST", "/trigger/invalid-discount-type"),
    "3": ("GET", "/trigger/async-price-fetch"),
    "bug3": ("GET", "/trigger/async-price-fetch"),
    "async-price-fetch": ("GET", "/trigger/async-price-fetch"),
}


@router.get("/errors/latest")
async def latest_error() -> dict[str, Any]:
    """
    Return the last error captured while proxying a buggy-app trigger.

    buggy-app itself does not expose /errors/latest (by design in Step 1);
    this endpoint surfaces whatever the API captured from the upstream 500.
    """
    payload = get_latest_buggy_error()
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No captured buggy-app error yet. Trigger a bug via "
                "POST /api/buggy-app/trigger/{bug_id}, or paste a traceback "
                "manually into POST /api/analyze."
            ),
        )
    return payload


@router.post("/trigger/{bug_id}", response_model=BuggyTriggerResponse)
async def trigger_bug(bug_id: str, body: dict[str, Any] | None = None) -> BuggyTriggerResponse:
    mapping = BUG_ENDPOINTS.get(bug_id)
    if mapping is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown bug_id '{bug_id}'. Known: {sorted(set(BUG_ENDPOINTS))}",
        )

    method, path = mapping
    base = get_settings().buggy_app_base_url.rstrip("/")
    url = f"{base}{path}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                response = await client.get(url, params=(body or {}))
            else:
                response = await client.request(method, url, json=body or {})
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach buggy-app at {base}: {exc}",
        ) from exc

    detail: Any
    try:
        detail = response.json()
    except Exception:
        detail = response.text

    if response.status_code >= 400:
        set_latest_buggy_error(
            {
                "bug_id": bug_id,
                "upstream_url": url,
                "upstream_status": response.status_code,
                "detail": detail,
                "note": (
                    "HTTP error body from buggy-app (full traceback is in the "
                    "buggy-app process console — copy it for /api/analyze)."
                ),
            }
        )

    return BuggyTriggerResponse(
        bug_id=bug_id,
        upstream_status=response.status_code,
        detail=detail,
        note=(
            "If this returned 500, copy the traceback from the buggy-app terminal "
            "and POST it to /api/analyze."
            if response.status_code >= 500
            else None
        ),
    )
