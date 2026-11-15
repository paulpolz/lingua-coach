"""One quota reservation per agent run, then ainvoke or the chat stream."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, TypeVar

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_llm_call
from app.services.agents.factory import RECURSION_LIMIT, CoachAgent, SchemaT
from app.services.agents.tools import AgentContext
from app.services.llm_usage import (
    LLMCallType,
    UsageStatus,
    _traced,
    _user_hash,
    complete,
    estimate_input_tokens,
    reserve_llm_call,
)

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_PUBLIC_DETAIL = {
    "LLM_TIMEOUT": "The coach took too long to answer. Please try again.",
    "LLM_QUOTA_EXCEEDED": "The coach is over its usage limit right now. Please try again later.",
    "LLM_SCHEMA_ERROR": "The coach sent an answer we could not read. Please try again.",
}


class LLMError(RuntimeError):
    def __init__(self, message: str, *, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code


def public_detail(code: str) -> str:
    """A learner-safe message for an LLM error code. Raw provider text stays in the logs."""
    return _PUBLIC_DETAIL.get(code, "The coach is unavailable right now. Please try again.")


class StreamItem:
    """One agent event before it is encoded as SSE."""

    __slots__ = ("data", "kind")

    def __init__(self, kind: str, data: Any) -> None:
        self.kind = kind
        self.data = data


def _error(exc: Exception) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return LLMError(f"Gemini request timed out after {settings.llm_timeout_seconds}s", code="LLM_TIMEOUT")
    if isinstance(exc, StructuredOutputValidationError):
        return LLMError("Gemini response did not match the schema", code="LLM_SCHEMA_ERROR")
    if "RESOURCE_EXHAUSTED" in str(exc):
        return LLMError(f"Gemini quota exceeded: {exc}", code="LLM_QUOTA_EXCEEDED")
    return LLMError(f"Gemini API error: {exc}", code="LLM_API_ERROR")


def require_structured(value: object, schema: type[T]) -> T:
    if isinstance(value, schema):
        return value
    raise LLMError("Gemini response did not match the schema", code="LLM_SCHEMA_ERROR")


def run_config(
    *,
    call_type: str,
    model_id: str,
    user_id: uuid.UUID,
    thread_id: uuid.UUID | None,
    trace_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "call_type": call_type,
        "model": model_id,
        "user_id_hash": _user_hash(user_id),
        **(trace_metadata or {}),
    }
    config: dict[str, Any] = {
        "run_name": call_type,
        "tags": [call_type, f"env:{settings.app_env}"],
        "metadata": metadata,
        "recursion_limit": RECURSION_LIMIT,
    }
    if thread_id is not None:
        config["configurable"] = {"thread_id": str(thread_id)}
    return config


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


def _message_usage(message: object) -> tuple[int, int] | None:
    """Completed-message usage. Token chunks repeat the same call and must not be summed."""
    if not isinstance(message, AIMessage) or isinstance(message, AIMessageChunk):
        return None
    usage = getattr(message, "usage_metadata", None) or {}
    if usage.get("input_tokens") is None:
        return None
    output = usage.get("output_tokens")
    return int(usage["input_tokens"]), int(output or 0)


def _add_usage(totals: list[int | None], message: object) -> None:
    counted = _message_usage(message)
    if counted is None:
        return
    totals[0] = (totals[0] or 0) + counted[0]
    totals[1] = (totals[1] or 0) + counted[1]


async def bootstrap_messages(agent: CoachAgent[Any], ctx: AgentContext, user_text: str) -> list:
    """Run this agent's tools once so the first model call already has them.

    Gemini rejects a function-call turn that does not follow a user turn (spike,
    14 Nov 2026), so the human message leads and the synthetic tool turn follows it.
    """
    messages: list = [HumanMessage(content=user_text)]
    calls = []
    tool_messages = []
    for spec in agent.tools:
        call_id = uuid.uuid4().hex
        calls.append({"name": spec.name, "args": {}, "id": call_id, "type": "tool_call"})
        tool_messages.append(ToolMessage(content=await spec.run(ctx), name=spec.name, tool_call_id=call_id))
    if not calls:
        return messages
    messages.append(AIMessage(content="", tool_calls=calls))
    messages.extend(tool_messages)
    return messages


def _estimate(agent: CoachAgent[Any], user_text: str, messages: list) -> int:
    parts = [agent.system_prompt, user_text]
    parts.extend(
        message.content for message in messages if isinstance(message, ToolMessage) and isinstance(message.content, str)
    )
    return estimate_input_tokens(*parts)


async def _prior_message_ids(agent: CoachAgent[Any], config: dict[str, Any]) -> set[str]:
    thread_id = (config.get("configurable") or {}).get("thread_id")
    if not thread_id:
        return set()
    snapshot = await agent.graph.aget_state(config)
    messages = (snapshot.values or {}).get("messages") or []
    return {message.id for message in messages if getattr(message, "id", None)}


def _sum_new_messages(messages: list, seen: set[str]) -> tuple[int | None, int | None]:
    totals: list[int | None] = [None, None]
    for message in messages:
        if getattr(message, "id", None) in seen:
            continue
        _add_usage(totals, message)
    return totals[0], totals[1]


async def invoke_agent(
    agent: CoachAgent[SchemaT],
    *,
    user_text: str,
    context: AgentContext,
    config: dict[str, Any],
) -> SchemaT:
    """One ainvoke inside the timeout. No quota row. Evals and the metered wrapper both use this shape."""
    messages = await bootstrap_messages(agent, context, user_text)
    async with asyncio.timeout(settings.llm_timeout_seconds):
        state = await agent.graph.ainvoke({"messages": messages}, config=config, context=context)
    return require_structured(state.get("structured_response"), agent.schema)


@_traced
async def metered_agent_run(
    db: AsyncSession,
    user_id: uuid.UUID,
    call_type: LLMCallType,
    *,
    agent: CoachAgent[SchemaT],
    user_text: str,
    context: AgentContext,
    thread_id: uuid.UUID | None = None,
    before_call: Callable[[], Awaitable[None]] | None = None,
    trace_metadata: Mapping[str, Any] | None = None,
) -> SchemaT:
    """Reserve one call, optionally save the user row, then return the schema instance.

    Inner model steps do not reserve again. Input tokens are the sum of completed
    AIMessage usage from this run only. A later persist failure stays with the caller,
    so the usage row is already `ok` or `error`.
    """
    messages = await bootstrap_messages(agent, context, user_text)
    event = await reserve_llm_call(
        db,
        user_id,
        call_type,
        estimated_input_tokens=_estimate(agent, user_text, messages),
    )
    if before_call is not None:
        await before_call()

    config = run_config(
        call_type=call_type,
        model_id=agent.model_id,
        user_id=user_id,
        thread_id=thread_id,
        trace_metadata=trace_metadata,
    )
    started = time.perf_counter()
    known: tuple[int | None, int | None] = (None, None)
    try:
        seen = await _prior_message_ids(agent, config)
        async with asyncio.timeout(settings.llm_timeout_seconds):
            state = await agent.graph.ainvoke({"messages": messages}, config=config, context=context)
        known = _sum_new_messages(list(state.get("messages") or []), seen)
        parsed = require_structured(state.get("structured_response"), agent.schema)
    except Exception as exc:
        await complete(db, event, input_tokens=known[0], status="error", model=agent.model_id)
        _record(call_type, agent.model_id, "error", started, (known[0] or 0, known[1] or 0))
        raise _error(exc) from exc
    await complete(db, event, input_tokens=known[0], status="ok", model=agent.model_id)
    _record(call_type, agent.model_id, "ok", started, (known[0] or 0, known[1] or 0))
    return parsed


def _token_delta(token: object, metadata: Mapping[str, Any]) -> str | None:
    """Learner-visible text. Schema JSON arrives as content blocks, not a plain string."""
    if metadata.get("langgraph_node") != "model":
        return None
    if getattr(token, "tool_call_chunks", None):
        return None
    content = getattr(token, "content", None)
    if isinstance(content, str) and content:
        return content
    return None


def _update_items(node_update: object, totals: list[int | None]) -> list[StreamItem]:
    if not isinstance(node_update, dict):
        return []
    items: list[StreamItem] = []
    for message in node_update.get("messages") or []:
        _add_usage(totals, message)
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls and not isinstance(message, AIMessageChunk):
            items.extend(StreamItem("tool_start", call.get("name")) for call in tool_calls if call.get("name"))
        if isinstance(message, ToolMessage) and message.name:
            items.append(StreamItem("tool_end", message.name))
    return items


async def _stream_items(
    agent: CoachAgent[Any],
    messages: list,
    config: dict,
    context: AgentContext,
    totals: list[int | None],
):
    structured: BaseModel | None = None
    async for chunk in agent.graph.astream(
        {"messages": messages},
        stream_mode=["messages", "updates"],
        version="v2",
        config=config,
        context=context,
    ):
        kind = chunk["type"]
        data = chunk["data"]
        if kind == "messages":
            token, metadata = data
            delta = _token_delta(token, metadata)
            if delta is not None:
                yield StreamItem("token", delta)
            continue
        if kind != "updates" or not isinstance(data, dict):
            continue
        for node_update in data.values():
            for item in _update_items(node_update, totals):
                yield item
            if isinstance(node_update, dict) and node_update.get("structured_response") is not None:
                structured = require_structured(node_update["structured_response"], agent.schema)
    if structured is None:
        raise LLMError("Gemini response did not match the schema", code="LLM_SCHEMA_ERROR")
    yield StreamItem("structured", structured)


@_traced
async def metered_agent_stream(
    db: AsyncSession,
    user_id: uuid.UUID,
    call_type: LLMCallType,
    *,
    agent: CoachAgent[Any],
    user_text: str,
    context: AgentContext,
    thread_id: uuid.UUID | None = None,
    before_call: Callable[[], Awaitable[None]] | None = None,
    trace_metadata: Mapping[str, Any] | None = None,
) -> AsyncIterator[StreamItem]:
    """Reserve one call, then return token, tool, and one structured item.

    Await this before the HTTP response is committed. A quota refusal raises
    here, from `reserve_llm_call`. The iterator finishes that same row and
    raises `LLMError` when the model call fails. Does not write `chat_messages`
    and does not emit SSE.
    """
    messages = await bootstrap_messages(agent, context, user_text)
    event = await reserve_llm_call(
        db,
        user_id,
        call_type,
        estimated_input_tokens=_estimate(agent, user_text, messages),
    )
    if before_call is not None:
        await before_call()

    config = run_config(
        call_type=call_type,
        model_id=agent.model_id,
        user_id=user_id,
        thread_id=thread_id,
        trace_metadata=trace_metadata,
    )
    started = time.perf_counter()
    totals: list[int | None] = [None, None]

    async def generate() -> AsyncIterator[StreamItem]:
        status: UsageStatus = "error"
        try:
            async with asyncio.timeout(settings.llm_timeout_seconds):
                async for item in _stream_items(agent, messages, config, context, totals):
                    yield item
            status = "ok"
        except Exception as exc:
            raise _error(exc) from exc
        finally:
            await complete(db, event, input_tokens=totals[0], status=status, model=agent.model_id)
            _record(call_type, agent.model_id, status, started, (totals[0] or 0, totals[1] or 0))

    return generate()
