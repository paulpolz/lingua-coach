# LangChain agent notes

Shipped behavior for the four coach agents. The manager approved the backend and the frontend. Checkpointer-primary history is [05-postgres-checkpointer.md](05-postgres-checkpointer.md). Streamed structured output is [04-chat-streaming.md](04-chat-streaming.md). Those two decisions do not need another ADR.

`docs/tech_requirements/rag.md` is a separate document and was not part of this migration. No RAG, embeddings, pgvector, or LangChain retrievers were built.

Docs read on 14 Nov 2026:

- [Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [Structured output](https://docs.langchain.com/oss/python/langchain/structured-output) and [`ResponseFormat`](https://reference.langchain.com/python/langchain/agents/structured_output/ResponseFormat)
- [`create_agent`](https://reference.langchain.com/python/langchain/agents/factory/create_agent)
- [Models](https://docs.langchain.com/oss/python/langchain/models) (`init_chat_model`)
- [Tools](https://docs.langchain.com/oss/python/langchain/tools)
- [Streaming](https://docs.langchain.com/oss/python/langchain/streaming)
- [Context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering) (`wrap_model_call`)
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) and [Postgres reference](https://reference.langchain.com/python/langgraph/checkpoints)

| Note | Capability |
|------|------------|
| [01-agent-factory.md](01-agent-factory.md) | `init_chat_model` + `create_agent` + `ResponseFormat` |
| [02-tools.md](02-tools.md) | Skill and SQL context tools |
| [03-metered-agent-run.md](03-metered-agent-run.md) | One reserve per run, summed tokens, existing `LLMError` codes |
| [04-chat-streaming.md](04-chat-streaming.md) | SSE chat; `ainvoke` for curriculum and report |
| [05-postgres-checkpointer.md](05-postgres-checkpointer.md) | `AsyncPostgresSaver`, projection into `chat_messages` |

Chat agents take the process checkpointer. Curriculum and report agents do not. SSE is off until `CHAT_STREAMING_ENABLED` is set; the JSON route stays available either way.

## APIs to use

- `langchain.chat_models.init_chat_model("google_genai:{model_id}", api_key=..., max_retries=0)`
- `langchain.agents.create_agent(..., response_format=ProviderStrategy(schema), checkpointer=...)`
- `ProviderStrategy` from `langchain.agents.structured_output` (a `ResponseFormat` value)
- `@tool` + `ToolRuntime` context
- Chat: `agent.astream(..., stream_mode=["messages", "updates"], version="v2")`
- Curriculum and report: `await agent.ainvoke(...)` inside `asyncio.timeout`
- `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`

## Spike the code depends on

`tests/manual/agent_spike.py` records the 14 Nov 2026 run against `gemini-3.5-flash-lite` and local Postgres. Production follows those results:

1. **Async saver.** `AsyncPostgresSaver.from_conn_string` stayed open for two `ainvoke` turns on one `thread_id`. `setup()` twice was a no-op. The lifespan holds that saver for the process.
2. **`structured_response` on `updates`.** With tools bound, an `updates` chunk carried the Pydantic model. `ProviderStrategy` stayed. `values` also had it; the runner does not subscribe to `values`. The public mode list stays `["messages", "updates"]` with `version="v2"`.
3. **Tokens.** Completed `AIMessage`s on `updates` had `usage_metadata["input_tokens"]`. Message chunks repeated usage, so the runner sums completed messages only. A missing count leaves `input_tokens=None` and the usage row keeps the reserve estimate.
4. **Reply text.** Model token chunks were lists of JSON text blocks, not `reply.content`. `CHAT_STREAM_REPLY_FALLBACK` (default true) emits one `token` from `structured_response.content` when no plain-string token arrived.
5. **Bootstrap order.** A function-call turn before the human message is `INVALID_ARGUMENT`. Bootstrap puts the human message first, then one `AIMessage` with the tool calls.
