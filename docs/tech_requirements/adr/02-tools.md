# Tools

Replace the preloaded skill markdown and context blocks with tools. Tools are ordinary SQL and file reads. They are not retrievers.

## API

Docs: [Tools](https://docs.langchain.com/oss/python/langchain/tools), [Runtime context](https://docs.langchain.com/oss/python/langchain/tools#access-context).

```python
from langchain.tools import ToolRuntime, tool

@tool
def fetch_ranked_mistakes(runtime: ToolRuntime[AgentContext]) -> str:
    """Return this learner's ranked open mistakes. Call before teaching or generating a lesson."""
    ...
```

`ToolRuntime` is injected by the agent. It is not a model-visible argument. Pass server data on invoke:

```python
agent.ainvoke(
    {"messages": [{"role": "user", "content": user_text}]},
    context=AgentContext(user_id=..., lesson_id=..., session_id=..., call_type=...),
    config={"configurable": {"thread_id": str(session_id)}},
)
```

`AgentContext` is a dataclass (`context_schema=` on `create_agent`). It holds the ids the HTTP layer or job already authorized. Tools open or receive the existing `AsyncSession` from context and query with those ids.

| Tool | Returns | Agents |
|------|---------|--------|
| `load_onboarding_interviewer` | `load_skill("onboarding_interviewer")` | onboarding |
| `load_course_composer` | `load_skill("course_composer")` | onboarding |
| `load_exercise_tutor` | `load_skill("exercise_tutor")` | lesson chat, curriculum |
| `load_report_writer` | `load_skill("report_writer")` | report |
| `language_policy` | `prompt_assembly.language_policy(...)` | all |
| `fetch_lesson_curriculum_and_profile` | today's `lesson_context_block` inputs | lesson chat |
| `fetch_ranked_mistakes` | `rank_mistakes` then `mistake_lines` | lesson chat (`k=CHAT_MISTAKES`), curriculum (`k=GENERATION_MISTAKES`) |
| `fetch_generation_context` | the dict `lesson_generation` builds now (roadmap, prior lessons, mistakes) | curriculum |
| `fetch_report_context` | session summary, this lesson's mistakes, `trim_log_sections` on report bodies | report |

No tool takes `user_id`, `session_id`, or `lesson_id`. Focus text for `rank_mistakes` comes from the stored curriculum or plan, not from the model. `language_policy` reads native, target, and the onboarding flag from context.

Skill tools return the markdown unchanged. They are the instructions. Context tools that contain learner sentences or earlier model logs wrap the body in `learner_memory()` from `prompt_assembly.py`. Keep `log_context_tokens` with the same block names.

`fetch_ranked_mistakes` calls `memory.rank_mistakes`. Do not reimplement the score. Do not add embeddings.

System prompt: "Call the tools for this turn before answering." That is the whole instruction about tools.

`AGENT_BOOTSTRAP_CONTEXT` defaults to true. When true, the runner executes that agent's tools once so the first model call already has them. The user `HumanMessage` leads. One `AIMessage` with matching `tool_calls` and the `ToolMessage`s follow it. Gemini rejects a function-call turn that does not follow a user turn (spike, 14 Nov 2026). Skill tools are included so pedagogy is present without a model round-trip. When false, the model calls the tools itself. There is one orchestration path.

## Do not use

- Retrievers, `VectorStore`, embeddings, pgvector, or anything described in `docs/tech_requirements/rag.md`.
- `InjectedState`, `InjectedStore`, `get_runtime()`, and `BaseStore`. Context is `ToolRuntime`.
- Model-written SQL or shell. Tools call existing functions.
- Stuffing `get_system_instruction()` back into `system_prompt`.
- Dynamic tool middleware, `FilesystemMiddleware`, or `SkillsMiddleware`. The skill files are already on disk; `@tool` wrappers are enough.

## Map onto this repo

`lesson_context_block`, `generation_user_prompt`, and `report_user_prompt` stay in `prompt_assembly.py`. Tools call them and return the string. The agent input is the learner's new message (chat) or a one-line job instruction (curriculum: `Generate the next lesson curriculum.`; report: `Patch the reports for the lesson that just finished.`), plus the bootstrap tool turn when the flag is on. The human message is first.

`rank_mistakes`, `CHAT_MISTAKES`, `GENERATION_MISTAKES`, and `prior_lesson_line` stay in `memory.py`. `trim_log_sections` stays in `report_ops.py`. `load_skill` stays in `skills.py`.

## Security

- Authorization stays in the caller (`get_owned` on chat, the job's `user_id` on background work). Tools must not accept an id from the model. A tool argument that selected a row would be an IDOR.
- Learner text, mistake examples, and report bodies are data. Fence them with `learner_memory()`. The system prompt is not a security boundary. Skill markdown is trusted repo content and is not fenced.
- Tool results still go through the schema and the existing writers (`_persist_turn`, `apply_report_op`). Keep the report-writer rule that rejects `patch_section` on log sections.
- Do not put tool bodies, API keys, or raw user ids in trace metadata or info logs. Token counts via `log_context_tokens` are enough.
- Production tracing stays off.

## Files

- New: `apps/backend/app/services/agents/tools.py` (thin wrappers and `AgentContext`)
- Call, do not rewrite: `skills.py`, `prompt_assembly.py` (`language_policy`, `learner_memory`, `lesson_context_block`, `generation_user_prompt`, `report_user_prompt`), `memory.py`, `report_ops.py`, `lesson_generation.py` (context dict)
- Flag: `AGENT_BOOTSTRAP_CONTEXT` on `Settings`, default true
