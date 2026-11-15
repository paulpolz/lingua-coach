# Agent factory and ResponseFormat

One factory builds all four agents. Each run reads `state["structured_response"]`, checks it is the Pydantic model, and persists `model_dump()` through the existing chat, lesson, and report code. There is no repair call.

## API

Docs: [Models](https://docs.langchain.com/oss/python/langchain/models), [Agents](https://docs.langchain.com/oss/python/langchain/agents), [Structured output](https://docs.langchain.com/oss/python/langchain/structured-output), [`create_agent`](https://reference.langchain.com/python/langchain/agents/factory/create_agent), [`ResponseFormat`](https://reference.langchain.com/python/langchain/agents/structured_output/ResponseFormat), [`ProviderStrategy`](https://reference.langchain.com/python/langchain/agents/structured_output/ProviderStrategy).

`ResponseFormat` is a type alias (`ToolStrategy | ProviderStrategy | AutoStrategy`). It is not a constructor. The value to pass is `ProviderStrategy(schema)`.

```python
from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy, ResponseFormat
from langchain.chat_models import init_chat_model

model = init_chat_model(
    f"google_genai:{model_id}",
    api_key=settings.llm_api_key,
    max_retries=0,
)
response_format: ResponseFormat = ProviderStrategy(schema)  # existing Pydantic class
agent = create_agent(
    model,
    tools=tools,
    system_prompt=system_prompt,
    response_format=response_format,
    context_schema=AgentContext,
    checkpointer=checkpointer,  # chat agents only; None for curriculum and report
)
```

| Agent | Schema | Model setting | Checkpointer | Invoke |
|-------|--------|---------------|--------------|--------|
| `onboarding_agent` | `OnboardingReply` | `llm_model_chat` | yes | stream |
| `lesson_agent` | `LessonReply` | `llm_model_chat` | yes | stream |
| `curriculum_agent` | `LessonCurriculum` | `llm_model_lesson` | no | `ainvoke` |
| `report_agent` | `ReportPatch` | `llm_model_lesson` | no | `ainvoke` |

Cache one model per `model_id`, same as `_chat_model` today. Missing `llm_api_key` raises `LLMError(..., code="LLM_CONFIG_ERROR")` before any provider call.

The only timeout is `asyncio.timeout(settings.llm_timeout_seconds)` around the whole `ainvoke` or `astream` in the runner. `init_chat_model` has no `timeout=`. `CapContextWindow` is always attached and trims the model request in `wrap_model_call` / `awrap_model_call`.

After the run:

- Missing `structured_response`, a validation error, or a value that is not an instance of the schema: `LLM_SCHEMA_ERROR`.
- Then `model_dump()` into the existing persist path. Do not add a second semantic check. `schemas/llm.py` already ignores unknown keys.

System prompt is a few lines: role, call the tools before answering, one learner-facing turn. Pedagogy stays in `skills/*.md`, loaded by tools. Do not paste skill markdown into `system_prompt`.

LangSmith config stays the current `RunnableConfig`: `run_name=call_type`, tags `[call_type, f"env:{app_env}"]`, metadata `call_type`, `model`, `user_id_hash`, plus `session_type` / `lesson_number` when the caller has them. No prompt text in metadata.

## Do not use

- `ChatGoogleGenerativeAI` and `with_structured_output`. `structured_llm.py` is removed. `LLMError` and `public_detail` live in `runner.py`.
- A bare schema class as `response_format`. Auto-select can pick `ToolStrategy`, whose default `handle_errors=True` sends a retry to the model. That is a repair call.
- `ToolStrategy`. The 14 Nov 2026 spike showed `ProviderStrategy` and tools together put a validated model on `updates`. `handle_errors=True` stays unused.
- `create_react_agent`, prompted `response_format=("instructions", Schema)`, `create_deep_agent`, subagents, and `ModelRetryMiddleware`.
- `temperature=0.3` from `apps/backend/test.py`. Leave temperature unset, matching production today.
- A second `GOOGLE_API_KEY` env read. The key is `settings.llm_api_key`.

## Map onto this repo

The preserved contract is one schema, a runner sum of completed-message tokens, `asyncio.timeout`, and no repair. Schemas stay in `apps/backend/app/schemas/llm.py`. Call types stay `chat`, `lesson_json`, and `report`.

`build_agent(call_type, model_id, tools, system_prompt, schema, checkpointer)` lives in `app/services/agents/factory.py` and wraps `ProviderStrategy(schema)` itself. Per-agent modules only supply the tool list, the short prompt, and the schema.

## Security

- Pass `api_key` into `init_chat_model`. Do not log it or put it in trace metadata.
- Production tracing stays off. `Settings._check_deployment_safety` already rejects `LANGSMITH_TRACING` / `LANGCHAIN_TRACING_V2` when `APP_ENV=production`. Do not weaken that check. Traces contain full prompts.
- Metadata is `call_type` and `user_id_hash` (`llm_usage._user_hash`), not the raw user id and not learner text.
- `structured_response` is untrusted until it is an instance of the schema. Persist only `model_dump()` through `_persist_turn` / `report_ops`. Do not eval it or interpolate it into SQL.

## Files

- `apps/backend/app/services/agents/factory.py`, `onboarding.py`, `lesson_chat.py`, `curriculum.py`, `report.py`
- Schemas: `apps/backend/app/schemas/llm.py`
- Settings: `apps/backend/app/config.py` (`llm_model_chat`, `llm_model_lesson`, `llm_timeout_seconds`, `llm_api_key`)
- `apps/backend/app/services/structured_llm.py` is gone. `LLMError` and `public_detail` are imported from `runner.py`.
