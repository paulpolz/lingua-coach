"""One structured-output LLM call: one schema, one parse, no repair call.

Builds messages from `ChatTurn` history, calls `with_structured_output`, enforces the
timeout, records metrics and logs, maps failures to error codes, and returns a validated
Pydantic object. Provider: Gemini via `langchain-google-genai`; `_chat_model()` is the
only provider-specific seam (LangChain's `BaseChatModel` is the abstraction).
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_llm_call

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)
OnUsage = Callable[[int], Awaitable[None]] | None


class LLMError(RuntimeError):
    def __init__(self, message: str, *, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code


_PUBLIC_DETAIL = {
    "LLM_TIMEOUT": "The coach took too long to answer. Please try again.",
    "LLM_QUOTA_EXCEEDED": "The coach is over its usage limit right now. Please try again later.",
    "LLM_SCHEMA_ERROR": "The coach sent an answer we could not read. Please try again.",
}


def public_detail(code: str) -> str:
    """A learner-safe message for an LLM error code. Raw provider text stays in the logs."""
    return _PUBLIC_DETAIL.get(code, "The coach is unavailable right now. Please try again.")


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "model"]
    text: str


@functools.cache
def _chat_model(model_id: str) -> ChatGoogleGenerativeAI:
    """One client per model id, reused across calls."""
    if not settings.llm_api_key:
        raise LLMError("LLM_API_KEY is not configured", code="LLM_CONFIG_ERROR")
    # max_retries=0 so a quota failure surfaces instead of being retried away.
    # No response_mime_type here; with_structured_output supplies the schema.
    # No client timeout: asyncio.timeout in generate_structured is the single limit.
    return ChatGoogleGenerativeAI(model=model_id, api_key=settings.llm_api_key, temperature=None, max_retries=0)


def _messages(system_instruction: str, history: list[ChatTurn]) -> list:
    return [SystemMessage(content=system_instruction)] + [
        HumanMessage(content=t.text) if t.role == "user" else AIMessage(content=t.text) for t in history
    ]


def _tokens(message: object) -> tuple[int, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def _record(call_type: str, model: str, status: str, started: float, tokens: tuple[int, int] = (0, 0)) -> None:
    duration = time.perf_counter() - started
    record_llm_call(
        call_type=call_type,
        model=model,
        status=status,
        duration_seconds=duration,
        input_tokens=tokens[0],
        output_tokens=tokens[1],
    )
    logger.info(
        "llm_call",
        extra={
            "event": "llm_call",
            "call_type": call_type,
            "model": model,
            "status": status,
            "latency_ms": round(duration * 1000, 2),
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
        },
    )


def _error(exc: Exception) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return LLMError(f"Gemini request timed out after {settings.llm_timeout_seconds}s", code="LLM_TIMEOUT")
    if "RESOURCE_EXHAUSTED" in str(exc):
        return LLMError(f"Gemini quota exceeded: {exc}", code="LLM_QUOTA_EXCEEDED")
    return LLMError(f"Gemini API error: {exc}", code="LLM_API_ERROR")


async def generate_structured(
    *,
    model_id: str,
    schema: type[T],
    system_instruction: str,
    history: list[ChatTurn],
    call_type: str,
    on_usage: OnUsage = None,
    trace_metadata: Mapping[str, Any] | None = None,
) -> T:
    """Return a parsed model. Does not touch the quota row.

    A finished call invokes `on_usage` with the raw input count, then returns
    `parsed` or raises `LLM_SCHEMA_ERROR`. Transport failures are recorded with
    zero tokens and do not call `on_usage`. There is no repair call.
    """
    started = time.perf_counter()
    try:
        chat = _chat_model(model_id).with_structured_output(schema, method="json_schema", include_raw=True)
        # Picked up by LangSmith when LANGSMITH_TRACING is on; inert otherwise.
        config: RunnableConfig = {
            "run_name": call_type,
            "tags": [call_type, f"env:{settings.app_env}"],
            "metadata": {"call_type": call_type, "model": model_id, **(trace_metadata or {})},
        }
        # The only timeout: it bounds the whole call, whatever the transport does.
        async with asyncio.timeout(settings.llm_timeout_seconds):
            result = await chat.ainvoke(_messages(system_instruction, history), config=config)
    except Exception as exc:  # noqa: BLE001
        _record(call_type, model_id, "error", started)
        raise _error(exc) from exc

    # include_raw yields {"raw", "parsed", "parsing_error"}.
    raw = parsed = None
    parsing_error: object = result
    if isinstance(result, dict):
        raw = result.get("raw")
        parsed = result.get("parsed")
        parsing_error = result.get("parsing_error")
    tokens = _tokens(raw)
    if on_usage is not None:
        await on_usage(tokens[0])
    if parsing_error is not None or not isinstance(parsed, schema):
        _record(call_type, model_id, "error", started, tokens)
        logger.warning(
            "llm_schema_error",
            extra={
                "event": "llm_schema_error",
                "call_type": call_type,
                "model": model_id,
                "error": (str(parsing_error)[:500] if parsing_error else "parsed output was not the schema"),
            },
        )
        raise LLMError("Gemini response did not match the schema", code="LLM_SCHEMA_ERROR")
    _record(call_type, model_id, "ok", started, tokens)
    return parsed
