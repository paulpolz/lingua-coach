"""A queue-driven stand-in for the coach chat model. Never calls a real provider.

The agent builds its model with `init_chat_model`. Tests patch that function, so
`ainvoke` / `astream` on the compiled graph run against this fake. Queue a
Pydantic reply, an exception, `SchemaMismatch`, or a `ToolRound`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables.config import var_child_runnable_config
from pydantic import BaseModel

RAW_INPUT_TOKENS = 42
RAW_OUTPUT_TOKENS = 7


class SchemaMismatch:
    """Queue item: the provider answered, but the text is not the schema."""


@dataclass
class ToolRound:
    """One tool call, then the queued reply on the next model step.

    `text` is learner-visible and is emitted as a token when it is non-empty.
    The schema itself is returned as content blocks, matching the Gemini spike.
    """

    reply: BaseModel
    tool_name: str
    text: str = ""
    sent: bool = False


@dataclass
class LLMCall:
    schema: type[BaseModel] | None
    messages: list[Any]
    config: dict[str, Any] | None
    structured_kwargs: dict[str, Any]

    @property
    def text(self) -> str:
        return "\n".join(_as_text(message.content) for message in self.messages)


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                value = block.get("text", block.get("content", ""))
                parts.append(value if isinstance(value, str) else str(value))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


QueueItem = BaseModel | Exception | SchemaMismatch | ToolRound | Callable[[LLMCall], Awaitable[Any]]


def _usage(tokens: int) -> dict[str, int]:
    return {
        "input_tokens": tokens,
        "output_tokens": RAW_OUTPUT_TOKENS,
        "total_tokens": tokens + RAW_OUTPUT_TOKENS,
    }


def _schema_message(model: BaseModel, tokens: int) -> AIMessage:
    body = json.dumps(model.model_dump(mode="json"))
    return AIMessage(
        content=[{"type": "text", "text": body}],
        usage_metadata=_usage(tokens),
        id=uuid.uuid4().hex,
    )


def _snapshot(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not config:
        return None
    copied = dict(config)
    for key in ("metadata", "configurable"):
        value = copied.get(key)
        if isinstance(value, dict):
            copied[key] = dict(value)
    tags = copied.get("tags")
    if isinstance(tags, list):
        copied["tags"] = list(tags)
    return copied


@dataclass
class FakeLLM:
    queue: list[QueueItem] = field(default_factory=list)
    calls: list[LLMCall] = field(default_factory=list)
    init_kwargs: list[dict[str, Any]] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    bind_kwargs: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = RAW_INPUT_TOKENS

    def push(self, *items: QueueItem) -> FakeLLM:
        self.queue.extend(items)
        return self

    async def answer(self, messages: list[BaseMessage]) -> AIMessage:
        call = LLMCall(
            schema=None,
            messages=list(messages),
            config=_snapshot(var_child_runnable_config.get()),
            structured_kwargs=dict(self.bind_kwargs),
        )
        self.calls.append(call)
        if not self.queue:
            raise AssertionError("fake_llm queue is empty")
        item: Any = self.queue.pop(0)
        if callable(item) and not isinstance(item, BaseModel):
            item = await item(call)
        if isinstance(item, ToolRound) and not item.sent:
            item.sent = True
            self.queue.insert(0, item)
            return AIMessage(
                content=item.text,
                tool_calls=[{"name": item.tool_name, "args": {}, "id": uuid.uuid4().hex, "type": "tool_call"}],
                usage_metadata=_usage(self.input_tokens),
                id=uuid.uuid4().hex,
            )
        if isinstance(item, ToolRound):
            item = item.reply
        if isinstance(item, Exception):
            raise item
        if isinstance(item, SchemaMismatch):
            return AIMessage(
                content=[{"type": "text", "text": "not-json"}],
                usage_metadata=_usage(self.input_tokens),
                id=uuid.uuid4().hex,
            )
        if isinstance(item, BaseModel):
            call.schema = type(item)
            return _schema_message(item, self.input_tokens)
        raise AssertionError(f"unsupported fake_llm queue item: {item!r}")


def _chat_model(fake: FakeLLM) -> BaseChatModel:
    class _Model(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake-coach"

        def bind_tools(self, tools: Any, *, tool_choice: str | None = None, **kwargs: Any) -> Any:
            fake.bind_kwargs = dict(kwargs)
            return self.bind(tools=list(tools), tool_choice=tool_choice, **kwargs)

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            raise NotImplementedError("the fake coach model is async")

        async def _agenerate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            # The agent calls `ainvoke`. This LangChain build does not stream that call
            # unless `_astream` is overridden, so a batch run shows up only here.
            fake.modes.append("ainvoke")
            message = await fake.answer(messages)
            return ChatResult(generations=[ChatGeneration(message=message)])

    return _Model()


@contextmanager
def install_fake_llm(fake: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLM]:
    from app.services.agents.factory import _cached_model

    def build(*args: Any, **kwargs: Any) -> BaseChatModel:
        model_name = args[0] if args else kwargs.get("model")
        fake.init_kwargs.append({"model": model_name, **kwargs})
        return _chat_model(fake)

    _cached_model.cache_clear()
    monkeypatch.setattr("app.services.agents.factory.init_chat_model", build)
    try:
        yield fake
    finally:
        _cached_model.cache_clear()
