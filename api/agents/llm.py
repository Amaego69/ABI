"""Shared Anthropic LLM helpers with Langfuse generation tracing."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel

from api.config import get_settings
from api.observability import observation

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _extract_json(text: str) -> dict:
    """Parse JSON from a model reply, tolerating markdown fences and leading prose."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model response — cannot parse JSON")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Find the first JSON object/array in the text
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise


def get_anthropic_client():
    import anthropic

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _usage_details(message: Any) -> dict[str, int] | None:
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    details: dict[str, int] = {}
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if input_tokens is not None:
        details["input"] = int(input_tokens)
    if output_tokens is not None:
        details["output"] = int(output_tokens)
    cache_read = getattr(usage, "cache_read_input_tokens", None)
    if cache_read:
        details["cache_read_input_tokens"] = int(cache_read)
    return details or None


def _message_text(message: Any) -> str:
    """Extract visible text from an Anthropic message (skip thinking blocks)."""
    parts: list[str] = []
    for block in message.content or []:
        block_type = getattr(block, "type", None)
        if block_type == "thinking":
            continue
        if block_type == "text" or hasattr(block, "text"):
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _tool_input(message: Any, tool_name: str) -> dict | None:
    for block in message.content or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            raw = getattr(block, "input", None)
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                return _extract_json(raw)
    return None


def _supports_thinking_disable(model: str) -> bool:
    m = model.lower()
    return any(token in m for token in ("sonnet-5", "opus-5", "haiku-5", "fable-5", "mythos"))


def _create_message(client, *, model: str, max_tokens: int, system: str, user: str, **extra: Any):
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        **extra,
    }
    if _supports_thinking_disable(model):
        kwargs["thinking"] = {"type": "disabled"}
    try:
        return client.messages.create(**kwargs)
    except Exception as exc:
        # Older SDK / model combo may reject thinking= — retry without it
        if "thinking" in kwargs and "thinking" in str(exc).lower():
            kwargs.pop("thinking", None)
            return client.messages.create(**kwargs)
        raise


def call_structured(
    *,
    system: str,
    user: str,
    schema: type[T],
    trace_name: str = "structured_call",
) -> T:
    """
    Call Claude and parse the response into a Pydantic model.

    Uses forced tool_use for reliable structured output (critical on Sonnet 5,
    where adaptive thinking can otherwise consume the whole budget).
    """
    settings = get_settings()
    client = get_anthropic_client()

    schema_json = schema.model_json_schema()
    tool_name = "emit_result"
    full_system = (
        f"{system}\n\n"
        f"You MUST call the `{tool_name}` tool with a payload that matches the schema. "
        "Do not answer in free text."
    )
    prompt_input = {"system": full_system, "user": user, "schema": schema.__name__}

    with observation(
        trace_name,
        as_type="generation",
        input=prompt_input,
        metadata={"schema": schema.__name__, "agent": trace_name},
        model=settings.anthropic_model,
        model_parameters={"max_tokens": 8192, "tool_choice": tool_name},
    ) as gen:
        message = _create_message(
            client,
            model=settings.anthropic_model,
            max_tokens=8192,
            system=full_system,
            user=user,
            tools=[
                {
                    "name": tool_name,
                    "description": f"Return the structured {schema.__name__} result",
                    "input_schema": schema_json,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )

        data = _tool_input(message, tool_name)
        raw = _message_text(message)
        if data is None:
            # Fallback: parse text JSON if the model ignored tool_choice
            data = _extract_json(raw)

        parsed = schema.model_validate(data)

        if gen is not None:
            update_kwargs: dict[str, Any] = {
                "output": data,
                "metadata": {
                    "schema": schema.__name__,
                    "raw_preview": (raw or json.dumps(data))[:2000],
                    "stop_reason": getattr(message, "stop_reason", None),
                },
            }
            usage = _usage_details(message)
            if usage:
                update_kwargs["usage_details"] = usage
            gen.update(**update_kwargs)

        return parsed


def call_text(*, system: str, user: str, max_tokens: int = 4096) -> str:
    """Call Claude and return plain text (Langfuse generation when enabled)."""
    settings = get_settings()
    client = get_anthropic_client()

    with observation(
        "llm_text",
        as_type="generation",
        input={"system": system, "user": user},
        model=settings.anthropic_model,
        model_parameters={"max_tokens": max_tokens},
    ) as gen:
        message = _create_message(
            client,
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system,
            user=user,
        )
        text = _message_text(message)

        if gen is not None:
            update_kwargs: dict[str, Any] = {"output": text[:4000]}
            usage = _usage_details(message)
            if usage:
                update_kwargs["usage_details"] = usage
            gen.update(**update_kwargs)

        return text
