"""Single Gemini API client wrapper (`generateContent`, streamed for chat).

Two model configs from settings (`GEMINI_MODEL_CHAT`, `GEMINI_MODEL_LESSON`)
per docs/tech_requirements/ai-api.md. One provider, one client — no
multi-provider abstraction in MVP.

On timeout/failure, every public function raises `GeminiError`; the API layer
maps this to SSE `error` events (chat) or HTTP `502` (lesson generation,
Phase 3).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import types
from google.genai.errors import APIError as GenAIAPIError

from app.config import settings


class GeminiError(RuntimeError):
    """Raised on any Gemini request failure or timeout."""


@dataclass(frozen=True)
class ChatTurn:
    """One turn of conversational history for a Gemini `contents` list.

    `role` is Gemini's own turn role, not the app's `chat_messages.role` —
    the assistant's turn is `"model"`, not `"assistant"`.
    """

    role: Literal["user", "model"]
    text: str


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise GeminiError("GEMINI_API_KEY is not configured")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _to_contents(history: list[ChatTurn]) -> list[types.Content]:
    return [
        types.Content(role=turn.role, parts=[types.Part.from_text(text=turn.text)])
        for turn in history
    ]


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

    try:
        async with asyncio.timeout(timeout):
            stream = await client.aio.models.generate_content_stream(
                model=model_id,
                contents=_to_contents(history),
                config=types.GenerateContentConfig(system_instruction=system_instruction),
            )
            async for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    yield text
    except TimeoutError as exc:
        raise GeminiError(f"Gemini request timed out after {timeout}s") from exc
    except GenAIAPIError as exc:
        raise GeminiError(f"Gemini API error: {exc}") from exc
    except GeminiError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize all failures to GeminiError
        raise GeminiError(f"Gemini request failed: {exc}") from exc


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
        raise GeminiError(f"Gemini request timed out after {timeout}s") from exc
    except GenAIAPIError as exc:
        raise GeminiError(f"Gemini API error: {exc}") from exc
    except GeminiError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize all failures to GeminiError
        raise GeminiError(f"Gemini request failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not text:
        raise GeminiError("Gemini returned an empty response for a JSON-mode request")
    return text
