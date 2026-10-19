"""Gemini calls for chat and lesson JSON.

`stream_chat` and `generate_json` are the only public entry points. Both use
LangChain's `ChatGoogleGenerativeAI`. Callers, including graph nodes, keep
these signatures. Failures raise `GeminiError`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from google.genai.errors import APIError as GenAIAPIError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import (
    ChatGoogleGenerativeAIError,
    GoogleContextOverflowError,
    GoogleRateLimitError,
)

from app.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_llm_call

logger = get_logger(__name__)


class GeminiError(RuntimeError):
    """Raised on any Gemini request failure or timeout.

    `code` is a machine-readable SSE/API error code (e.g. `LLM_TIMEOUT`).
    `error_type` is a short metrics label (`timeout`, `api_error`, …).
    """

    def __init__(self, message: str, *, code: str = "LLM_ERROR", error_type: str = "error") -> None:
        super().__init__(message)
        self.code = code
        self.error_type = error_type


@dataclass(frozen=True)
class ChatTurn:
    """One turn of conversational history.

    `role` is Gemini's turn role, not the app's `chat_messages.role` —
    the assistant's turn is `"model"`, not `"assistant"`.
    """

    role: Literal["user", "model"]
    text: str


_CONTEXT_LIMIT_MARKERS = (
    "context length",
    "maximum context",
    "token limit",
    "too many tokens",
    "context_length",
)


def _schema_dict(response_schema: object | None) -> dict | None:
    if response_schema is None:
        return None
    if isinstance(response_schema, dict):
        return response_schema
    model_json_schema = getattr(response_schema, "model_json_schema", None)
    if callable(model_json_schema):
        schema = model_json_schema()
        if isinstance(schema, dict):
            return schema
    raise GeminiError(
        "response_schema must be a dict or a Pydantic model",
        code="LLM_CONFIG_ERROR",
        error_type="config_error",
    )


def _chat_model(
    *,
    model_id: str,
    timeout: float,
    json_mode: bool,
    response_schema: object | None,
) -> ChatGoogleGenerativeAI:
    if not settings.gemini_api_key:
        raise GeminiError(
            "GEMINI_API_KEY is not configured",
            code="LLM_CONFIG_ERROR",
            error_type="config_error",
        )
    # temperature=None leaves Gemini's default in place; the wrapper otherwise
    # sends 0.7. max_retries=0 so a quota failure is not retried away.
    kwargs: dict = {
        "model": model_id,
        "api_key": settings.gemini_api_key,
        "temperature": None,
        "max_retries": 0,
        "timeout": timeout,
    }
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
        schema = _schema_dict(response_schema)
        if schema is not None:
            kwargs["response_schema"] = schema
    return ChatGoogleGenerativeAI(**kwargs)


def _messages(system_instruction: str, history: list[ChatTurn]) -> list:
    messages: list = []
    if system_instruction:
        messages.append(SystemMessage(content=system_instruction))
    for turn in history:
        if turn.role == "user":
            messages.append(HumanMessage(content=turn.text))
        else:
            messages.append(AIMessage(content=turn.text))
    return messages


def _message_text(message: object) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        text = getattr(message, "text", None)
        return text if isinstance(text, str) else ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _iter_causes(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


def _is_quota(exc: BaseException) -> bool:
    if isinstance(exc, GoogleRateLimitError):
        return True
    status = str(getattr(exc, "status", None) or "")
    message = str(exc)
    return status == "RESOURCE_EXHAUSTED" or "RESOURCE_EXHAUSTED" in message


def _is_context_limit(exc: BaseException) -> bool:
    if isinstance(exc, GoogleContextOverflowError):
        return True
    message = str(exc)
    lowered = message.lower()
    return any(marker.lower() in lowered or marker in message for marker in _CONTEXT_LIMIT_MARKERS)


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map a LangChain-wrapped Gemini failure onto the existing error codes."""
    chain = list(_iter_causes(exc))
    if any(_is_timeout(item) for item in chain):
        return "LLM_TIMEOUT", "timeout"
    if any(_is_context_limit(item) for item in chain if isinstance(item, GoogleContextOverflowError)):
        return "LLM_CONTEXT_LIMIT", "context_limit"
    if any(_is_quota(item) for item in chain):
        return "LLM_QUOTA_EXCEEDED", "quota"
    if any(_is_context_limit(item) for item in chain):
        return "LLM_CONTEXT_LIMIT", "context_limit"
    if any(isinstance(item, (ChatGoogleGenerativeAIError, GenAIAPIError)) for item in chain):
        return "LLM_API_ERROR", "api_error"
    return "LLM_ERROR", "error"


def _usage_tokens(usage: object | None) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_token_count") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("candidates_token_count") or 0)
    if not output_tokens and input_tokens:
        total = int(usage.get("total_tokens") or usage.get("total_token_count") or 0)
        output_tokens = max(total - input_tokens, 0)
    return input_tokens, output_tokens


def _emit_llm_observability(
    *,
    call_type: str,
    model: str,
    status: str,
    duration_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error_type: str | None = None,
) -> None:
    record_llm_call(
        call_type=call_type,
        model=model,
        status=status,
        duration_seconds=duration_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    logger.info(
        "llm_call",
        extra={
            "event": "llm_call",
            "provider": "gemini",
            "call_type": call_type,
            "model": model,
            "status": status,
            "latency_ms": round(duration_seconds * 1000, 2),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "error_type": error_type,
        },
    )


def _failure(
    exc: BaseException,
    *,
    call_type: str,
    model: str,
    started: float,
    timeout: float,
) -> GeminiError:
    if isinstance(exc, GeminiError):
        _emit_llm_observability(
            call_type=call_type,
            model=model,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type=exc.error_type,
        )
        return exc
    code, error_type = _classify_exception(exc)
    _emit_llm_observability(
        call_type=call_type,
        model=model,
        status="error",
        duration_seconds=time.perf_counter() - started,
        error_type=error_type,
    )
    if code == "LLM_TIMEOUT":
        message = f"Gemini request timed out after {timeout}s"
    elif code == "LLM_ERROR":
        message = f"Gemini request failed: {exc}"
    else:
        message = f"Gemini API error: {exc}"
    return GeminiError(message, code=code, error_type=error_type)


async def _note_usage(
    message: object,
    on_usage: Callable[[int], Awaitable[None]] | None,
) -> tuple[int, int]:
    usage = getattr(message, "usage_metadata", None)
    input_tokens, output_tokens = _usage_tokens(usage)
    if usage is not None and on_usage is not None:
        await on_usage(input_tokens)
    return input_tokens, output_tokens


async def stream_chat(
    *,
    system_instruction: str,
    history: list[ChatTurn],
    model: str | None = None,
    timeout_seconds: float | None = None,
    on_usage: Callable[[int], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    """Stream a chat completion, yielding text chunks as they arrive.

    `history` must already include the new user turn as its last entry.
    Raises `GeminiError` on timeout or any upstream failure — callers (the
    chat SSE route) turn this into an `event: error` frame.
    """
    model_id = model or settings.gemini_model_chat
    timeout = timeout_seconds if timeout_seconds is not None else settings.gemini_timeout_seconds
    chat = _chat_model(
        model_id=model_id,
        timeout=timeout,
        json_mode=False,
        response_schema=None,
    )
    messages = _messages(system_instruction, history)
    call_type = "chat"
    started = time.perf_counter()
    input_tokens = 0
    output_tokens = 0

    try:
        async with asyncio.timeout(timeout):
            async for chunk in chat.astream(messages):
                # Gemini streams a running total. LangChain stores the delta, so a
                # later chunk often has input_tokens == 0. Sum every chunk.
                chunk_in, chunk_out = _usage_tokens(getattr(chunk, "usage_metadata", None))
                input_tokens += chunk_in
                output_tokens += chunk_out
                text = _message_text(chunk)
                if text:
                    yield text
    except Exception as exc:  # noqa: BLE001 - normalize all failures to GeminiError
        raise _failure(exc, call_type=call_type, model=model_id, started=started, timeout=timeout) from exc

    if on_usage is not None:
        await on_usage(input_tokens)
    _emit_llm_observability(
        call_type=call_type,
        model=model_id,
        status="ok",
        duration_seconds=time.perf_counter() - started,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def generate_json(
    *,
    system_instruction: str,
    history: list[ChatTurn],
    model: str | None = None,
    timeout_seconds: float | None = None,
    response_schema: type | None = None,
    on_usage: Callable[[int], Awaitable[None]] | None = None,
) -> str:
    """Non-streaming JSON-mode completion.

    Returns the raw JSON text. This function does not retry or validate
    against the caller's schema — lesson generation's one repair lives in
    the lesson graph. Raises `GeminiError` on timeout or any upstream
    failure, exactly like `stream_chat`.
    """
    model_id = model or settings.gemini_model_lesson
    timeout = timeout_seconds if timeout_seconds is not None else settings.gemini_timeout_seconds
    chat = _chat_model(
        model_id=model_id,
        timeout=timeout,
        json_mode=True,
        response_schema=response_schema,
    )
    messages = _messages(system_instruction, history)
    call_type = "lesson_json"
    started = time.perf_counter()

    try:
        async with asyncio.timeout(timeout):
            response = await chat.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 - normalize all failures to GeminiError
        raise _failure(exc, call_type=call_type, model=model_id, started=started, timeout=timeout) from exc

    input_tokens, output_tokens = await _note_usage(response, on_usage)
    text = _message_text(response)
    if not text:
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_type="empty_response",
        )
        raise GeminiError(
            "Gemini returned an empty response for a JSON-mode request",
            code="LLM_EMPTY_RESPONSE",
            error_type="empty_response",
        )

    _emit_llm_observability(
        call_type=call_type,
        model=model_id,
        status="ok",
        duration_seconds=time.perf_counter() - started,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return text
