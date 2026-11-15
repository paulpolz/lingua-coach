# Postgres checkpointer

The agent reads and writes history on a LangGraph thread. The UI reads `chat_messages`. After a successful turn the runner projects the learner-visible pair into `chat_messages`.

## API

Docs: [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers), [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [`AsyncPostgresSaver`](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver).

FastAPI is async, so the saver is `AsyncPostgresSaver`. Pin `langgraph-checkpoint-postgres`. Build the URL from `settings.database_url` by replacing `+asyncpg` with the plain `postgresql://` driver, the same swap Alembic already makes for psycopg. Do not share the SQLAlchemy asyncpg pool. The saver uses its own psycopg connection.

Open it in a FastAPI lifespan and hold the context manager until shutdown:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(postgres_url) as checkpointer:
    await checkpointer.setup()
    app.state.checkpointer = checkpointer
    yield
```

`setup()` creates LangGraph's checkpoint tables. Do not hand-write that DDL in Alembic. `setup()` on each boot is fine if the spike shows it is idempotent.

Pass the saver only to `onboarding_agent` and `lesson_agent`:

```python
config = {
    "configurable": {"thread_id": str(session_id)},
    "recursion_limit": 15,
}
inputs = {"messages": [{"role": "user", "content": content}]}
```

`thread_id` is the chat session id. A UUID string is under the 255-character column limit. A new user message is that one `HumanMessage`. The checkpointer appends it to the thread. Do not load the last N rows from `chat_messages` and resend them.

Cap what the model sees without deleting the thread. Docs show `RemoveMessage(REMOVE_ALL_MESSAGES)` in `@before_model`, which rewrites the checkpoint. Do not use that. Use `@wrap_model_call` and `request.override(messages=...)`, which is transient ([context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering)). Keep the newest messages that cover `settings.chat_context_messages` learner turns (human plus the assistant reply), including the `ToolMessage`s that belong to those turns. If the cut would split a tool call from its `ToolMessage`, move the cut back to the previous `HumanMessage`.

Projection, same order as today:

1. `before_call` commits the user `ChatMessage` before the agent runs.
2. On success, `_persist_turn` then insert the assistant row: `content` from `structured_response.content`, `metadata_json` from `TurnMetadata` (not the raw checkpoint).
3. On agent failure, leave the user row and write no assistant row.
4. `GET .../messages` keeps reading `chat_messages` only.

Curriculum and report agents get `checkpointer=None`. They are one shot.

Reload is option A: the UI is `chat_messages`. A repair job that rebuilds rows from the checkpoint is out of this slice.

## Do not use

- `InMemorySaver` outside tests.
- Sync `PostgresSaver` inside async routes.
- `thread_id` equal to the user id. Sessions must not share a thread.
- Copying the LangChain message array, tool transcripts, or checkpoint blobs into `metadata_json`.
- Exposing a checkpoint read API to the client.
- Deleting checkpoint rows as the context cap.

## Map onto this repo

The agent does not load `chat_messages` to rebuild the prompt. `chat_messages` stays for the list API, the finish session summary, and `active_minutes` (timestamps on those rows). Tool messages stay in the checkpoint so the list API never shows them. Accept and finish delete the `chat_messages` and the `chat_sessions` row. They do not call `adelete_thread`.

`ChatMessage` / `ChatSession` models stay. Projection uses the existing insert in `chat.py`.

## Security

- The HTTP layer is the auth boundary. Every invoke checks `get_owned` before using `thread_id`. Knowing a session UUID must not be enough; the checkpointer has no user column.
- Checkpoint rows contain learner text and tool output. They live in the app database. Do not ship them to LangSmith in production (tracing stays off) and do not log them.
- `adelete_thread` is not part of this slice. When account deletion is implemented later, it must delete the thread for each of that user's session ids as well as `chat_messages`.
- Fenced learner data is a prompt rule for tools, not a property of the checkpointer. The model still sees tool output on later turns inside the cap. Tools must keep fencing on every call.

## Files

- `apps/backend/app/services/agents/checkpointer.py` (URL swap, lifespan helper). `setup()` on each boot is idempotent (spike, 14 Nov 2026)
- `apps/backend/app/main.py` holds the saver on `app.state.checkpointer`. A missing saver is `503` `CHECKPOINTER_UNAVAILABLE` before the reserve
- `apps/backend/app/api/v1/chat.py` projects with `_save_user_message` and `_save_assistant`. There is no `project.py`
- `langgraph-checkpoint-postgres` is in `apps/backend/pyproject.toml`
- Readers: `apps/backend/app/models/chat.py`, `list_chat_messages`, `lesson_timing.active_minutes`
- Cap middleware: `CapContextWindow` in `apps/backend/app/services/agents/factory.py` (`wrap_model_call` / `awrap_model_call`)
