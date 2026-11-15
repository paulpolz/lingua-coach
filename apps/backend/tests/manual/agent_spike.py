"""Manual spikes for the three LangChain risks. Not collected by pytest.

Run from apps/backend:

    uv run python tests/manual/agent_spike.py

Needs LLM_API_KEY and Postgres (docker compose postgres). Prints findings only.

Results from 14 Nov 2026 against gemini-3.5-flash-lite and local Postgres:

1. AsyncPostgresSaver.from_conn_string stayed open for two ainvoke turns on one
   thread_id. setup() twice was a no-op. The second turn still had the first
   human message. Production holds the saver in the FastAPI lifespan.
2. stream_mode ["messages", "updates"] version v2: an updates chunk carried
   structured_response as the Pydantic model while tools were bound.
   ProviderStrategy stayed. values also had it; the runner does not subscribe
   to values.
3. Completed AIMessages on updates had usage_metadata input_tokens (46 then 73
   on the two model steps). Message chunks repeated and zeroed usage, so the
   runner sums updates only.
4. Model token chunks were lists of JSON text blocks, not reply.content.
   The only plain string was the tool node. chat_stream_reply_fallback stays
   on and emits one token from structured_response.content.
5. A function-call turn before the human message is INVALID_ARGUMENT. Bootstrap
   puts the human message first, then one AIMessage with the tool calls.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MODEL_ID = os.environ.get("LLM_MODEL_CHAT", "gemini-3.5-flash-lite")


class SpikeReply(BaseModel):
    content: str = Field(description="One short sentence for the learner.")
    note: str = Field(description="One word: ok")


@tool
def language_hint() -> str:
    """Return the language to answer in. Call this before answering."""
    return "Answer in English."


def _postgres_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://lingua:lingua@localhost:5432/lingua_coach")
    return url.replace("+asyncpg", "").replace("postgresql+psycopg://", "postgresql://")


def _usage(message: object) -> dict:
    usage = getattr(message, "usage_metadata", None) or {}
    return {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}


async def _stream_probe(model) -> dict:
    agent = create_agent(
        model,
        tools=[language_hint],
        system_prompt="Call the tool, then answer with the schema. One short sentence.",
        response_format=ProviderStrategy(SpikeReply),
    )
    inputs = {"messages": [{"role": "user", "content": "Say hello in one sentence."}]}
    findings: dict = {
        "provider_strategy_error": None,
        "update_has_structured": False,
        "values_has_structured": False,
        "message_content_kinds": [],
        "message_content_samples": [],
        "update_usages": [],
        "chunk_usages": [],
    }
    try:
        async for chunk in agent.astream(
            inputs,
            stream_mode=["messages", "updates", "values"],
            version="v2",
        ):
            kind = chunk["type"]
            data = chunk["data"]
            if kind == "updates" and isinstance(data, dict):
                for node_update in data.values():
                    if not isinstance(node_update, dict):
                        continue
                    if node_update.get("structured_response") is not None:
                        findings["update_has_structured"] = True
                        findings["structured_type"] = type(node_update["structured_response"]).__name__
                    for message in node_update.get("messages") or []:
                        if isinstance(message, AIMessage) and not isinstance(message, AIMessageChunk):
                            findings["update_usages"].append(_usage(message))
            elif kind == "values" and isinstance(data, dict) and data.get("structured_response") is not None:
                findings["values_has_structured"] = True
            elif kind == "messages":
                token, _metadata = data
                content = getattr(token, "content", None)
                findings["message_content_kinds"].append(type(content).__name__)
                if isinstance(content, str) and content.strip():
                    findings["message_content_samples"].append(content[:80])
                usage = _usage(token)
                if usage["input_tokens"] is not None:
                    findings["chunk_usages"].append(usage)
    except Exception as exc:  # noqa: BLE001 — spike records the provider failure
        findings["provider_strategy_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return findings


async def _checkpointer_probe(model) -> dict:
    url = _postgres_url()
    thread_id = f"spike-{uuid.uuid4()}"
    findings: dict = {"setup_twice": False, "second_turn_sees_first": False, "error": None}
    try:
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            await saver.setup()
            findings["setup_twice"] = True
            agent = create_agent(
                model,
                tools=[language_hint],
                system_prompt="Call the tool, then answer with the schema.",
                response_format=ProviderStrategy(SpikeReply),
                checkpointer=saver,
            )
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 15}
            first = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "Remember the code word cedar."}]},
                config=config,
            )
            second = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "What code word did I just give you?"}]},
                config=config,
            )
            texts = []
            for state in (first, second):
                for message in state.get("messages") or []:
                    content = getattr(message, "content", "")
                    if isinstance(content, str):
                        texts.append(content)
            blob = " ".join(texts).lower()
            human_count = sum(1 for message in second.get("messages") or [] if getattr(message, "type", "") == "human")
            findings["second_turn_message_count"] = len(second.get("messages") or [])
            findings["second_turn_human_count"] = human_count
            findings["second_turn_sees_first"] = "cedar" in blob and human_count >= 2
            usages = [
                _usage(message)
                for message in second.get("messages") or []
                if isinstance(message, AIMessage) and not isinstance(message, AIMessageChunk)
            ]
            findings["ainvoke_usages"] = usages
    except Exception as exc:  # noqa: BLE001
        findings["error"] = f"{type(exc).__name__}: {exc}"[:500]
    return findings


async def main() -> None:
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise SystemExit("LLM_API_KEY is not set")
    model = init_chat_model(f"google_genai:{MODEL_ID}", api_key=api_key, max_retries=0)
    stream = await _stream_probe(model)
    checkpoint = await _checkpointer_probe(model)
    print("STREAM")
    for key, value in stream.items():
        print(f"  {key}: {value}")
    print("CHECKPOINTER")
    for key, value in checkpoint.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
