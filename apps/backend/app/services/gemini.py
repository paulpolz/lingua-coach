"""Single Gemini API client wrapper (`generateContent`, streamed for chat).

Two model configs from settings (`GEMINI_MODEL_CHAT`, `GEMINI_MODEL_LESSON`)
per docs/tech_requirements/ai-api.md. One provider, one client — no
multi-provider abstraction in MVP.

On timeout/failure, every public function raises `GeminiError`; the API layer
maps this to SSE `error` events (chat) or HTTP `502` (lesson generation,
Phase 3).

Also records Prometheus LLM metrics and structured `llm_call` logs (tokens,
latency, status) when available from Gemini `usage_metadata`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import types
from google.genai.errors import APIError as GenAIAPIError

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
    """One turn of conversational history for a Gemini `contents` list.

    `role` is Gemini's own turn role, not the app's `chat_messages.role` —
    the assistant's turn is `"model"`, not `"assistant"`.
    """

    role: Literal["user", "model"]
    text: str


_client: genai.Client | None = None

_CONTEXT_LIMIT_MARKERS = (
    "context length",
    "maximum context",
    "token limit",
    "too many tokens",
    "context_length",
    "RESOURCE_EXHAUSTED",
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise GeminiError(
                "GEMINI_API_KEY is not configured",
                code="LLM_CONFIG_ERROR",
                error_type="config_error",
            )
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _to_contents(history: list[ChatTurn]) -> list[types.Content]:
    return [
        types.Content(role=turn.role, parts=[types.Part.from_text(text=turn.text)])
        for turn in history
    ]


def _classify_genai_error(exc: GenAIAPIError) -> tuple[str, str]:
    message = str(exc)
    lowered = message.lower()
    if any(marker.lower() in lowered or marker in message for marker in _CONTEXT_LIMIT_MARKERS):
        return "LLM_CONTEXT_LIMIT", "context_limit"
    return "LLM_API_ERROR", "api_error"


def _usage_tokens(usage: object | None) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    input_tokens = int(getattr(usage, "prompt_token_count", None) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", None) or 0)
    if not output_tokens:
        total = int(getattr(usage, "total_token_count", None) or 0)
        if total and input_tokens:
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


async def stream_chat(
    *,
    system_instruction: str,
    history: list[ChatTurn],
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> AsyncIterator[str]:
    """Stream a chat completion, yielding text chunks as they arrive.

    `history` must already include the new user turn as its last entry.
    Raises `GeminiError` on timeout or any upstream failure — callers (the
    chat SSE route) turn this into an `event: error` frame.
    """
    client = _get_client()
    model_id = model or settings.gemini_model_chat
    timeout = timeout_seconds if timeout_seconds is not None else settings.gemini_timeout_seconds
    call_type = "chat"
    started = time.perf_counter()
    input_tokens = 0
    output_tokens = 0

    try:
        async with asyncio.timeout(timeout):
            stream = await client.aio.models.generate_content_stream(
                model=model_id,
                contents=_to_contents(history),
                config=types.GenerateContentConfig(system_instruction=system_instruction),
            )
            async for chunk in stream:
                usage = getattr(chunk, "usage_metadata", None)
                if usage is not None:
                    input_tokens, output_tokens = _usage_tokens(usage)
                text = getattr(chunk, "text", None)
                if text:
                    yield text
    except TimeoutError as exc:
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type="timeout",
        )
        raise GeminiError(
            f"Gemini request timed out after {timeout}s",
            code="LLM_TIMEOUT",
            error_type="timeout",
        ) from exc
    except GenAIAPIError as exc:
        code, error_type = _classify_genai_error(exc)
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type=error_type,
        )
        raise GeminiError(f"Gemini API error: {exc}", code=code, error_type=error_type) from exc
    except GeminiError as exc:
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type=exc.error_type,
        )
        raise
    except Exception as exc:  # noqa: BLE001 - normalize all failures to GeminiError
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type="error",
        )
        raise GeminiError(f"Gemini request failed: {exc}", code="LLM_ERROR", error_type="error") from exc

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
) -> str:
    """Non-streaming JSON-mode completion for lesson generation
    (ai-api.md "Structured lesson output"): one `generateContent` call,
    `response_mime_type="application/json"` (+ `response_schema` when a
    Pydantic model is passed, for Gemini's structured-output mode), against
    `GEMINI_MODEL_LESSON` by default.

    Returns the raw JSON text; this function does **not** retry or validate
    against the caller's schema — the one-repair-retry loop and Pydantic
    validation live in app/services/lesson_generation.py, which calls this
    twice at most per generation. Raises `GeminiError` on timeout or any
    upstream failure, exactly like `stream_chat`.
    """
    client = _get_client()
    model_id = model or settings.gemini_model_lesson
    timeout = timeout_seconds if timeout_seconds is not None else settings.gemini_timeout_seconds
    call_type = "lesson_json"
    started = time.perf_counter()

    config_kwargs: dict = {
        "system_instruction": system_instruction,
        "response_mime_type": "application/json",
    }
    if response_schema is not None:
        config_kwargs["response_schema"] = response_schema

    try:
        async with asyncio.timeout(timeout):
            response = await client.aio.models.generate_content(
                model=model_id,
                contents=_to_contents(history),
                config=types.GenerateContentConfig(**config_kwargs),
            )
    except TimeoutError as exc:
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type="timeout",
        )
        raise GeminiError(
            f"Gemini request timed out after {timeout}s",
            code="LLM_TIMEOUT",
            error_type="timeout",
        ) from exc
    except GenAIAPIError as exc:
        code, error_type = _classify_genai_error(exc)
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type=error_type,
        )
        raise GeminiError(f"Gemini API error: {exc}", code=code, error_type=error_type) from exc
    except GeminiError as exc:
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type=exc.error_type,
        )
        raise
    except Exception as exc:  # noqa: BLE001 - normalize all failures to GeminiError
        _emit_llm_observability(
            call_type=call_type,
            model=model_id,
            status="error",
            duration_seconds=time.perf_counter() - started,
            error_type="error",
        )
        raise GeminiError(f"Gemini request failed: {exc}", code="LLM_ERROR", error_type="error") from exc

    input_tokens, output_tokens = _usage_tokens(getattr(response, "usage_metadata", None))
    text = getattr(response, "text", None)
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
