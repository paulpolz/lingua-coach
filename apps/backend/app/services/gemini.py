"""Gemini via LangChain: `stream_chat` for coach turns, `generate_json` for lesson and report JSON."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_llm_call

logger = get_logger(__name__)

OnUsage = Callable[[int], Awaitable[None]] | None


class GeminiError(RuntimeError):
    def __init__(self, message: str, *, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "model"]
    text: str


def _model(model_id: str, *, json_mode: bool) -> ChatGoogleGenerativeAI:
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured", code="LLM_CONFIG_ERROR")
    # max_retries=0 so a quota failure surfaces instead of being retried away.
    kwargs: dict = {
        "model": model_id,
        "api_key": settings.gemini_api_key,
        "temperature": None,
        "max_retries": 0,
        "timeout": settings.gemini_timeout_seconds,
    }
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    return ChatGoogleGenerativeAI(**kwargs)


def _messages(system_instruction: str, history: list[ChatTurn]) -> list:
    return [SystemMessage(content=system_instruction)] + [
        HumanMessage(content=t.text) if t.role == "user" else AIMessage(content=t.text) for t in history
    ]


def _text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return "".join(b if isinstance(b, str) else str(b.get("text", "")) for b in content or [])


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


def _error(exc: Exception) -> GeminiError:
    if isinstance(exc, GeminiError):
        return exc
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return GeminiError(f"Gemini request timed out after {settings.gemini_timeout_seconds}s", code="LLM_TIMEOUT")
    if "RESOURCE_EXHAUSTED" in str(exc):
        return GeminiError(f"Gemini quota exceeded: {exc}", code="LLM_QUOTA_EXCEEDED")
    return GeminiError(f"Gemini API error: {exc}", code="LLM_API_ERROR")


async def stream_chat(
    *, system_instruction: str, history: list[ChatTurn], on_usage: OnUsage = None
) -> AsyncIterator[str]:
    """Yield text chunks. `history` ends with the new user turn. Raises GeminiError."""
    model_id = settings.gemini_model_chat
    started = time.perf_counter()
    input_tokens = output_tokens = 0
    try:
        chat = _model(model_id, json_mode=False)
        async with asyncio.timeout(settings.gemini_timeout_seconds):
            async for chunk in chat.astream(_messages(system_instruction, history)):
                # LangChain reports per-chunk deltas, so the totals are sums.
                chunk_in, chunk_out = _tokens(chunk)
                input_tokens += chunk_in
                output_tokens += chunk_out
                if text := _text(chunk):
                    yield text
    except Exception as exc:  # noqa: BLE001
        _record("chat", model_id, "error", started)
        raise _error(exc) from exc
    if on_usage is not None:
        await on_usage(input_tokens)
    _record("chat", model_id, "ok", started, (input_tokens, output_tokens))


async def generate_json(
    *,
    system_instruction: str,
    history: list[ChatTurn],
    on_usage: OnUsage = None,
    call_type: str = "lesson_json",
) -> str:
    """Return raw JSON text from a JSON-mode call. Raises GeminiError."""
    model_id = settings.gemini_model_lesson
    started = time.perf_counter()
    try:
        chat = _model(model_id, json_mode=True)
        async with asyncio.timeout(settings.gemini_timeout_seconds):
            response = await chat.ainvoke(_messages(system_instruction, history))
    except Exception as exc:  # noqa: BLE001
        _record(call_type, model_id, "error", started)
        raise _error(exc) from exc
    tokens = _tokens(response)
    if on_usage is not None:
        await on_usage(tokens[0])
    text = _text(response)
    if not text:
        _record(call_type, model_id, "error", started, tokens)
        raise GeminiError("Gemini returned an empty response", code="LLM_EMPTY_RESPONSE")
    _record(call_type, model_id, "ok", started, tokens)
    return text
