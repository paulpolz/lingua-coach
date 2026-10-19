"""Gemini error classification and the LangChain adapter's chunk/error contract."""

import asyncio

import pytest
from google.genai.errors import APIError as GenAIAPIError
from langchain_google_genai.chat_models import GoogleInvalidRequestError, GoogleRateLimitError

from app.config import settings
from app.services.gemini import (
    ChatTurn,
    GeminiError,
    _classify_exception,
    generate_json,
    stream_chat,
)


def test_resource_exhausted_maps_to_quota() -> None:
    exc = GenAIAPIError(
        429,
        {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}},
    )
    assert _classify_exception(exc) == ("LLM_QUOTA_EXCEEDED", "quota")


def test_wrapped_resource_exhausted_maps_to_quota() -> None:
    inner = GenAIAPIError(
        429,
        {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}},
    )
    outer = RuntimeError("langchain wrapped the provider error")
    outer.__cause__ = inner
    assert _classify_exception(outer) == ("LLM_QUOTA_EXCEEDED", "quota")


def test_langchain_rate_limit_maps_to_quota() -> None:
    exc = GoogleRateLimitError("Error calling model 'gemini' (RESOURCE_EXHAUSTED): Quota exceeded")
    assert _classify_exception(exc) == ("LLM_QUOTA_EXCEEDED", "quota")


def test_context_limit_is_not_classified_as_quota() -> None:
    exc = GenAIAPIError(
        400,
        {"error": {"status": "INVALID_ARGUMENT", "message": "maximum context length exceeded"}},
    )
    assert _classify_exception(exc) == ("LLM_CONTEXT_LIMIT", "context_limit")


def test_langchain_invalid_request_context_limit_is_not_quota() -> None:
    exc = GoogleInvalidRequestError(
        "Error calling model 'gemini' (INVALID_ARGUMENT): maximum context length exceeded"
    )
    assert _classify_exception(exc) == ("LLM_CONTEXT_LIMIT", "context_limit")


class _Chunk:
    def __init__(self, content: str, usage: dict | None = None) -> None:
        self.content = content
        self.usage_metadata = usage


class _FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        yield _Chunk("Hel")
        yield _Chunk("lo", {"input_tokens": 9, "output_tokens": 2})

    async def ainvoke(self, messages):
        self.calls += 1
        return _Chunk("")


@pytest.mark.asyncio
async def test_stream_chat_yields_each_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _FakeModel()
    monkeypatch.setattr("app.services.gemini._chat_model", lambda **_kw: model)
    seen: list[int] = []

    async def on_usage(prompt_token_count: int) -> None:
        seen.append(prompt_token_count)

    chunks = [
        chunk
        async for chunk in stream_chat(
            system_instruction="sys",
            history=[ChatTurn(role="user", text="hi")],
            on_usage=on_usage,
        )
    ]
    assert chunks == ["Hel", "lo"]
    assert seen == [9]


class _RunningTotalModel:
    async def astream(self, messages):
        yield _Chunk("Hel", {"input_tokens": 11})
        yield _Chunk("lo", {"input_tokens": 0, "output_tokens": 1})


@pytest.mark.asyncio
async def test_stream_chat_keeps_prompt_tokens_when_later_chunk_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.gemini._chat_model", lambda **_kw: _RunningTotalModel())
    seen: list[int] = []

    async def on_usage(prompt_token_count: int) -> None:
        seen.append(prompt_token_count)

    chunks = [
        chunk
        async for chunk in stream_chat(
            system_instruction="sys",
            history=[ChatTurn(role="user", text="hi")],
            on_usage=on_usage,
        )
    ]
    assert chunks == ["Hel", "lo"]
    assert seen == [11]


@pytest.mark.asyncio
async def test_generate_json_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.gemini._chat_model", lambda **_kw: _FakeModel())
    with pytest.raises(GeminiError) as exc:
        await generate_json(
            system_instruction="sys",
            history=[ChatTurn(role="user", text="hi")],
        )
    assert exc.value.code == "LLM_EMPTY_RESPONSE"


@pytest.mark.asyncio
async def test_missing_api_key_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(GeminiError) as exc:
        await generate_json(
            system_instruction="sys",
            history=[ChatTurn(role="user", text="hi")],
        )
    assert exc.value.code == "LLM_CONFIG_ERROR"


class _SlowModel:
    async def astream(self, messages):
        await asyncio.sleep(1)
        yield _Chunk("late")


@pytest.mark.asyncio
async def test_stream_chat_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.gemini._chat_model", lambda **_kw: _SlowModel())
    with pytest.raises(GeminiError) as exc:
        async for _chunk in stream_chat(
            system_instruction="sys",
            history=[ChatTurn(role="user", text="hi")],
            timeout_seconds=0.05,
        ):
            pass
    assert exc.value.code == "LLM_TIMEOUT"
