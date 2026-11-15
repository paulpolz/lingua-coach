"""One factory for the four coach agents."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.structured_output import ProviderStrategy, ResponseFormat
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import BaseModel

from app.config import settings
from app.services.agents.tools import AgentContext, ContextTool

# Enough for the bootstrap tools plus one answer.
RECURSION_LIMIT = 15

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class CoachAgent(Generic[SchemaT]):
    graph: Any
    tools: tuple[ContextTool, ...]
    system_prompt: str
    schema: type[SchemaT]
    model_id: str
    call_type: str


def _is_human(message: object) -> bool:
    if isinstance(message, HumanMessage):
        return True
    if isinstance(message, dict):
        return message.get("role") == "user" or message.get("type") == "human"
    return getattr(message, "type", None) == "human"


def _tool_call_ids(message: object) -> set[str]:
    calls = getattr(message, "tool_calls", None) or []
    found: set[str] = set()
    for call in calls:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id")
        if isinstance(call_id, str):
            found.add(call_id)
    return found


def _splits_tool_pair(messages: list, cut: int) -> bool:
    """True when a kept ToolMessage belongs to an AIMessage the cut dropped."""
    earlier: set[str] = set()
    for message in messages[:cut]:
        earlier.update(_tool_call_ids(message))
    for message in messages[cut:]:
        tool_call_id = getattr(message, "tool_call_id", None)
        if isinstance(message, ToolMessage) and tool_call_id in earlier:
            return True
    return False


def cap_messages(messages: list, max_turns: int) -> list:
    """Keep the newest learner turns. The checkpoint itself is not trimmed.

    A turn starts at a human message and includes the assistant reply and its tool
    messages. If the cut would separate a tool call from its result, it moves back
    to the previous human message.
    """
    if max_turns <= 0:
        return list(messages)
    human_at = [index for index, message in enumerate(messages) if _is_human(message)]
    if len(human_at) <= max_turns:
        return list(messages)
    cut = human_at[-max_turns]
    while cut > 0 and _splits_tool_pair(messages, cut):
        earlier = [index for index in human_at if index < cut]
        cut = earlier[-1] if earlier else 0
    return list(messages[cut:])


class CapContextWindow(AgentMiddleware[AgentState, AgentContext]):
    """Trim the model request. Does not rewrite the checkpoint."""

    tools: tuple = ()

    def _trimmed(self, request):
        kept = cap_messages(list(request.messages), settings.chat_context_messages)
        if len(kept) == len(request.messages):
            return request
        return request.override(messages=kept)

    def wrap_model_call(self, request, handler):
        return handler(self._trimmed(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._trimmed(request))


@functools.cache
def _cached_model(model_id: str):
    # No timeout here: asyncio.timeout around the whole run is the only limit.
    # Temperature stays unset, matching the previous chat client.
    return init_chat_model(f"google_genai:{model_id}", api_key=settings.llm_api_key, max_retries=0)


def get_model(model_id: str):
    from app.services.agents.runner import LLMError

    if not settings.llm_api_key:
        raise LLMError("LLM_API_KEY is not configured", code="LLM_CONFIG_ERROR")
    return _cached_model(model_id)


def build_agent(
    call_type: str,
    model_id: str,
    tools: tuple[ContextTool, ...],
    system_prompt: str,
    schema: type[SchemaT],
    checkpointer: Any | None,
) -> CoachAgent[SchemaT]:
    """Build one agent. Chat passes the process checkpointer; batch passes None.

    Spike (14 Nov 2026, gemini-3.5-flash-lite): ProviderStrategy and tools together
    put a validated model on the `updates` stream. ToolStrategy is not used.
    """
    response_format: ResponseFormat = ProviderStrategy(schema)
    graph = create_agent(
        get_model(model_id),
        tools=[item.tool for item in tools],
        system_prompt=system_prompt,
        response_format=response_format,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        middleware=[CapContextWindow()],
    )
    return CoachAgent(
        graph=graph,
        tools=tools,
        system_prompt=system_prompt,
        schema=schema,
        model_id=model_id,
        call_type=call_type,
    )
