"""A queue-driven stand-in for the LangChain chat model. Never calls a real provider.

`LLM_PATCH_TARGET` is the only place that names the provider class; every test reaches
the fake through `install_fake_llm`, so a module rename changes one constant.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

LLM_PATCH_TARGET = "app.services.gemini.ChatGoogleGenerativeAI"
RAW_INPUT_TOKENS = 42


class SchemaMismatch:
    """Queue item: the provider answered but the JSON did not parse into the schema."""


@dataclass
class LLMCall:
    schema: type[BaseModel]
    messages: list[Any]
    config: dict[str, Any] | None
    structured_kwargs: dict[str, Any]

    @property
    def text(self) -> str:
        return "\n".join(str(m.content) for m in self.messages)


QueueItem = BaseModel | Exception | SchemaMismatch | Callable[[LLMCall], Awaitable[Any]]


@dataclass
class FakeLLM:
    queue: list[QueueItem] = field(default_factory=list)
    calls: list[LLMCall] = field(default_factory=list)
    init_kwargs: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = RAW_INPUT_TOKENS

    def push(self, *items: QueueItem) -> FakeLLM:
        self.queue.extend(items)
        return self

    async def _answer(self, call: LLMCall) -> dict[str, Any]:
        self.calls.append(call)
        if not self.queue:
            raise AssertionError(f"fake_llm queue is empty (call for {call.schema.__name__})")
        item: Any = self.queue.pop(0)
        if callable(item) and not isinstance(item, BaseModel):
            item = await item(call)
        raw = SimpleNamespace(usage_metadata={"input_tokens": self.input_tokens, "output_tokens": 7})
        if isinstance(item, Exception):
            raise item
        if isinstance(item, SchemaMismatch):
            return {"raw": raw, "parsed": None, "parsing_error": ValueError("schema")}
        return {"raw": raw, "parsed": item, "parsing_error": None}


class _Structured:
    def __init__(self, fake: FakeLLM, schema: type[BaseModel], kwargs: dict[str, Any]) -> None:
        self._fake, self._schema, self._kwargs = fake, schema, kwargs

    async def ainvoke(self, messages: list[Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._fake._answer(LLMCall(self._schema, list(messages), config, self._kwargs))


def _fake_chat_model_class(fake: FakeLLM) -> Callable[..., Any]:
    def build(**kwargs: Any) -> SimpleNamespace:
        fake.init_kwargs.append(kwargs)
        return SimpleNamespace(
            with_structured_output=lambda schema, **kw: _Structured(fake, schema, kw),
        )

    return build


@contextmanager
def install_fake_llm(fake: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLM]:
    monkeypatch.setattr(LLM_PATCH_TARGET, _fake_chat_model_class(fake))
    yield fake
