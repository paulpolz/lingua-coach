# Chat streaming and batch invoke

Chat turns stream over SSE. Curriculum and report jobs stay one-shot `ainvoke`. Learning-plan and lesson-summary writes stay side effects of the validated `structured_response` inside `_persist_turn`. They are not extra endpoints.

## API

Docs: [Streaming](https://docs.langchain.com/oss/python/langchain/streaming). The plan requires `astream` with `stream_mode=["messages", "updates"]`. Current docs want `version="v2"` so every chunk is `{"type", "ns", "data"}`. Use that version. Do not adopt the newer event-streaming API (`stream.messages`, `astream_events`); the plan already fixed the mode list.

```python
async for chunk in agent.astream(
    inputs,
    stream_mode=["messages", "updates"],
    version="v2",
    config=config,
    context=context,
):
    ...
```

`chunk["type"] == "messages"`: `token, metadata = chunk["data"]`. Emit a `token` SSE event only when `metadata["langgraph_node"] == "model"` and the chunk is learner-visible text (`token.content` as a plain string). Skip `tool_call_chunks`, empty content, and reasoning blocks.

`chunk["type"] == "updates"`:

- A completed `AIMessage` with `tool_calls` → `tool_start` for each name (`AIMessageChunk` is skipped)
- `ToolMessage` → `tool_end` for that name
- `structured_response` is kept and yielded once, after the stream, as one `structured` item

The route holds that item. It emits any `token` and `tool_*` events as they arrive. It then emits one `structured` SSE event (`model_dump(mode="json")`), runs `_save_assistant` (`_persist_turn` plus the assistant row), and emits `done`. On `LLMError` during the stream, or `PERSIST_FAILED` after a valid reply, it emits `error` and stops. `error` replaces `done`.

SSE endpoint: `POST /api/v1/chat/sessions/{session_id}/messages/stream` with `Content-Type: text/event-stream`. `CHAT_STREAMING_ENABLED` defaults to false. When it is false the stream route returns `404` `STREAMING_DISABLED`. The JSON route `POST .../messages` stays available either way and calls `metered_agent_run`. The client tries the stream first and posts JSON only for that 404 code. One reservation per request, taken in `metered_agent_stream` and awaited before `StreamingResponse`, so a quota refusal is the HTTP status. A `StreamingResponse` would otherwise commit `200` before the body runs.

| Event | Data |
|-------|------|
| `token` | `{"delta": "..."}` |
| `tool_start` | `{"name": "..."}` |
| `tool_end` | `{"name": "..."}` |
| `structured` | `OnboardingReply` or `LessonReply` as JSON (`model_dump(mode="json")`) |
| `done` | `{"message_id": "..."}` |
| `error` | `{"code": "LLM_*" \| "PERSIST_FAILED", "detail": "<public_detail>"}` |

Order: zero or more `token` / `tool_*`, then one `structured`, then `done`. `error` replaces `done`. Do not send both.

The 14 Nov 2026 spike showed Gemini streams the schema as content blocks, not as `reply.content` prose. `_token_delta` forwards a chunk only when `langgraph_node` is `model` and `content` is a non-empty string. `CHAT_STREAM_REPLY_FALLBACK` defaults to true: if no such token arrived, the route emits one `token` whose `delta` is `reply.content`, then the `structured` event. The UI uses `structured` for corrections, tips, roadmap, practiced, and `suggest_finish`. `timing` and the suggest-finish time gate are applied in `_save_assistant`, and the client reloads that row after `done`.

Curriculum (`run_lesson_generation_job`) and report (`run_report_update`) call `await agent.ainvoke(...)` inside the same timeout. They do not stream and do not take a checkpointer.

## Do not use

- `stream_mode="values"` from `apps/backend/test.py` as the production mode. `values` dumps the whole state, including tool transcripts.
- `model.stream` for the chat turn. The agent loop owns tools and `structured_response`.
- Streaming `structured_response` field-by-field, or streaming tool-argument JSON as `token` events.
- A second model call to turn JSON into prose.

## Map onto this repo

`post_chat_message` calls `metered_agent_run`, then `_save_assistant`, and returns `ChatTurnResponse`. The stream route does the same writes after the SSE `structured` event. `done.message_id` is the assistant `ChatMessage.id`. The frontend falls back to the JSON route when the stream answers `404` `STREAMING_DISABLED`, and does not fall back on other HTTP errors.

`list_chat_messages` is unchanged. It reads `chat_messages`, not the stream.

## Security

- Same auth as `post_chat_message`: `get_current_user`, `get_owned` on the session, onboarding and lesson checks, empty and `max_message_chars` checks, chat rate limit. SSE does not skip those.
- `error.detail` is `public_detail` or the existing persist sentence. No provider body, traceback, or tool payload.
- `token` deltas are the learner-facing reply only. Do not stream skill markdown or fenced memory.
- Production tracing stays off. A stream does not add a second trace that includes secrets.

## Files

- Stream helper: `metered_agent_stream` in `apps/backend/app/services/agents/runner.py`
- `apps/backend/app/api/v1/chat.py` encodes SSE. The JSON route always calls `metered_agent_run`
- Flags: `CHAT_STREAMING_ENABLED` (default false), `CHAT_STREAM_REPLY_FALLBACK` (default true)
- JSON response shape: `apps/backend/app/schemas/chat.py`
- Client: `apps/frontend/lib/chat-stream.ts`, `sendChatTurn` in `chat.ts`, `useChatTurn`
- Batch callers only: `lesson_generation.py`, `report_writer.py` (`ainvoke`)
