"""Langfuse observability helpers (Cloud free tier compatible).

When LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are set, LLM calls and pipeline
stages are traced so you can inspect reasoning chains, tokens, and retries in
the Langfuse dashboard. When unset, all helpers become no-ops.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from api.config import get_settings

logger = logging.getLogger(__name__)

_client = None
_client_failed = False


def _ensure_env() -> None:
    settings = get_settings()
    if settings.langfuse_public_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    if settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    if settings.langfuse_host:
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)


def get_langfuse():
    """Return a shared Langfuse client, or None if disabled / unavailable."""
    global _client, _client_failed

    settings = get_settings()
    if not settings.langfuse_enabled or _client_failed:
        return None
    if _client is not None:
        return _client

    try:
        _ensure_env()
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return _client
    except Exception:
        logger.exception("Failed to initialize Langfuse client — tracing disabled")
        _client_failed = True
        return None


def flush_langfuse() -> None:
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.exception("Langfuse flush failed")


def shutdown_langfuse() -> None:
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
        client.shutdown()
    except Exception:
        logger.exception("Langfuse shutdown failed")


@contextmanager
def observation(
    name: str,
    *,
    as_type: str = "span",
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
    model_parameters: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """
    Context manager around a Langfuse observation.

    Yields the observation object (with `.update()` / `.end()`) when enabled,
    otherwise yields None.
    """
    client = get_langfuse()
    if client is None:
        yield None
        return

    kwargs: dict[str, Any] = {
        "name": name,
        "as_type": as_type,
        "input": input,
        "metadata": metadata or {},
    }
    if model is not None:
        kwargs["model"] = model
    if model_parameters is not None:
        kwargs["model_parameters"] = model_parameters

    # Only swallow failures while *opening* the observation.
    # Exceptions from the caller's body must propagate (do not yield again).
    try:
        obs_cm = client.start_as_current_observation(**kwargs)
    except Exception:
        logger.exception(
            "Langfuse observation '%s' failed to start — continuing untraced", name
        )
        yield None
        return

    with obs_cm as obs:
        yield obs


def traced_callable(name: str, *, as_type: str = "agent"):
    """Decorator factory: wrap an agent/node function as a Langfuse observation."""

    def decorator(fn):
        def wrapper(state, *args, **kwargs):
            # Keep input small — full GraphState is huge
            summary = {
                "run_id": getattr(state, "run_id", None),
                "stage": getattr(state, "current_stage", None),
                "retry_count": getattr(state, "retry_count", None),
            }
            with observation(name, as_type=as_type, input=summary, metadata={"agent": name}) as obs:
                result = fn(state, *args, **kwargs)
                if obs is not None:
                    try:
                        out_summary = {
                            "keys": list(result.keys()) if isinstance(result, dict) else type(result).__name__,
                            "current_stage": (
                                result.get("current_stage") if isinstance(result, dict) else None
                            ),
                        }
                        obs.update(output=out_summary)
                    except Exception:
                        pass
                return result

        wrapper.__name__ = getattr(fn, "__name__", name)
        wrapper.__doc__ = getattr(fn, "__doc__", None)
        return wrapper

    return decorator
