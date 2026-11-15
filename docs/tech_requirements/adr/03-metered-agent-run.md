# metered_agent_run

One quota reservation covers the whole agent run. Inner model steps and tool calls do not reserve again. Input tokens from every model step are written onto that single `llm_usage` row.

## API

The wrapper stays next to the existing quota functions. It does not use a LangChain callback as the quota boundary.

```python
async def metered_agent_run(
    db, user_id, call_type, *, agent, user_text, context,
    thread_id=None, before_call=None, trace_metadata=None,
) -> BaseModel:
    messages = await bootstrap_messages(agent, context, user_text)
    event = await reserve_llm_call(db, user_id, call_type, estimated_input_tokens=estimate)
    if before_call is not None:
        await before_call()
    try:
        async with asyncio.timeout(settings.llm_timeout_seconds):
            state = await agent.graph.ainvoke({"messages": messages}, config=config, context=context)
        parsed = require_structured(state.get("structured_response"), schema)
    except Exception as exc:
        await complete(db, event, input_tokens=known_or_none, status="error", model=model_id)
        raise _error(exc) from exc
    await complete(db, event, input_tokens=summed_input_tokens, status="ok", model=model_id)
    return parsed
```

Chat streaming uses the same reserve and complete inside `metered_agent_stream`. The route awaits that function before it returns `StreamingResponse`, so a quota refusal is still an HTTP status. The iterator yields `StreamItem`s. It does not encode SSE and it does not write `chat_messages`. See [04-chat-streaming.md](04-chat-streaming.md).

Reservation estimate: character length of the system prompt, the new user text, and any bootstrap tool results, divided by 4 (`estimate_input_tokens`). After a finished `ainvoke`, `complete` stores the summed `usage_metadata["input_tokens"]` from completed `AIMessage`s in the final state whose ids were not already on the thread. The stream path sums completed `AIMessage`s on `updates` and skips `AIMessageChunk`s (chunks repeat the same usage). If no usage arrived, pass `input_tokens=None` so `complete` keeps the estimate.

`_error` keeps today's codes:

| Failure | Code |
|---------|------|
| `TimeoutError`, or a type name containing `timeout` | `LLM_TIMEOUT` |
| `RESOURCE_EXHAUSTED` in the provider text | `LLM_QUOTA_EXCEEDED` |
| Missing or invalid `structured_response`, including `StructuredOutputValidationError` | `LLM_SCHEMA_ERROR` |
| `LLM_API_KEY` missing | `LLM_CONFIG_ERROR` |
| Anything else from the provider | `LLM_API_ERROR` |

`public_detail` is unchanged. HTTP status stays `_LLM_STATUS` in `chat.py`. A later persist failure is still `PERSIST_FAILED` and does not flip the usage row (the row is already `ok` or `error` from the model call).

Set `recursion_limit` on the runnable config (LangGraph's step cap). 15 is enough for the bootstrap tools plus one answer. Do not add retry middleware.

Trace metadata: `user_id_hash` plus the caller's `trace_metadata`. `_traced` drops `db`, `user_id`, `before_call`, `context`, and `agent` from the trace inputs.

## Do not use

- `reserve_llm_call` inside tools, inside `wrap_model_call`, or once per model step.
- `get_usage_metadata_callback` as the source of truth. The 14 Nov 2026 spike showed completed `AIMessage.usage_metadata` on `updates`. The runner sums those messages. Chunks repeat the same usage.
- A repair invoke after `LLM_SCHEMA_ERROR`.
- `max_retries` greater than 0. Quota failures must surface.

## Map onto this repo

The contract is reserve, optional `before_call` (chat saves the user row here), run, `complete` as `ok` or `error`. `metered_structured_call` is gone. Callers:

- `post_chat_message`: `metered_agent_run`, `call_type="chat"`, `before_call` saves the user `ChatMessage`
- `stream_chat_message`: `metered_agent_stream`, same call type and `before_call`, awaited before the response body
- `run_lesson_generation_job`: `call_type="lesson_json"`, one reserve per job
- `run_report_update`: `call_type="report"`, one reserve per job

`check_and_record_user_limit(..., kind="chat")` stays in the HTTP handler, before reserve. Lesson-start limits stay in the lesson route. Do not move them into the agent.

Metrics: keep one `record_llm_call` per run, with the summed input tokens and the summed output tokens, status `ok` or `error`. Same log event name `llm_call`.

## Security

- The reserve is a quota control, not authorization. The route or job still checks the caller owns the session or lesson.
- Usage rows store counts, model id, call type, and user id. They do not store prompt text.
- Provider exception text stays in server logs (`str(exc)[:500]`). The client sees `public_detail(code)` only.
- Production tracing stays off. `user_id_hash` is the only learner identifier in trace metadata.

## Files

- `apps/backend/app/services/agents/runner.py` (`metered_agent_run`, `metered_agent_stream`, `_error`, token sum, `LLMError`, `public_detail`)
- `apps/backend/app/services/llm_usage.py` keeps `reserve_llm_call`, `complete`, `estimate_input_tokens`, `_user_hash`, and `_traced`
- Callers: `apps/backend/app/api/v1/chat.py`, `lesson_generation.py`, `report_writer.py`
- Evals call `invoke_agent` (same bootstrap and timeout, no quota row)
