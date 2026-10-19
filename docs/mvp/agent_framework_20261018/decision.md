# Agent framework migration

## Status

Accepted

## Date

2026-10-18

## Context

The tutor is one Gemini provider with two call shapes. Chat streams through `stream_chat`. Lesson generation and the report writer use `generate_json`. Pedagogy lives in skill markdown. Learner context is assembled from Postgres. Structured side data in chat is fenced JSON, parsed in `extraction.py`.

[ai-api.md](../init/tech_requirements/ai-api.md) is locked. Two sentences are in the way of this migration:

- Principle 2, "one Gemini client implementation," and the provider table row "Single Gemini SDK/HTTP client."
- The API-surface row "`generateContent` (stream for chat) — not Interactions API / managed agents."

The rest of that document stays. One provider. No second vendor. No managed agent server. Skill files remain the prompt store. Lesson JSON stays the curriculum contract.

Tests do not mock a framework. [conftest.py](../../../apps/backend/tests/conftest.py) patches `app.api.v1.chat.stream_chat` and `app.services.gemini.generate_json`. Lesson generation calls `gemini.generate_json` on the module in [lesson_generation.py](../../../apps/backend/app/services/lesson_generation.py), which is why the second patch works. [test_gemini_errors.py](../../../apps/backend/tests/test_gemini_errors.py) locks the quota and context-limit mapping.

[evals/run.py](../../../evals/run.py) is a custom harness of about 980 lines. `async_main`, `_run_case`, `_markdown_summary`, and `_maybe_judge` are the loop. The tests themselves are the YAML cases, [checks.py](../../../evals/checks.py), replay fixtures, and the judge rubrics.

Who this is for: the person maintaining this repo. Success is one shorter path for tutor execution and evals. Learners and CI see the same behavior.

## Decision

Three libraries, each in one place.

**LangChain** lives inside [gemini.py](../../../apps/backend/app/services/gemini.py). `ChatGoogleGenerativeAI` is how `stream_chat` and `generate_json` talk to Gemini. Callers, including graph nodes, keep calling those two functions. The raw `generate_content` and `generate_content_stream` calls go away. The duplicated timeout, metrics, and `GeminiError` handling copied between the two functions folds into one adapter. If `gemini.py` grows and both copies remain, the dependency comes back out.

**LangGraph** is the lesson-generation branch: build context, generate, validate, repair once or apply the catalog, persist. The production job invokes the graph. Nodes call `gemini.generate_json`. They do not build their own model. A chat graph ships only if [chat.py](../../../apps/backend/app/api/v1/chat.py) gets smaller and `app.api.v1.chat.stream_chat` is still the name the chat tests patch. Otherwise chat stays as it is.

**LangSmith** `Client.evaluate` / `aevaluate` is the eval orchestrator. It runs each example, calls the evaluators, and collects scores. `evals/run.py` becomes the entry point that loads YAML examples and calls `evaluate()`. It does not loop, write a report, or schedule judges. The target calls the lesson graph. `--replay` puts the frozen completion on graph state and skips the model node.

```text
FastAPI
  ├─ lesson job ── lesson_generation StateGraph ── gemini.generate_json ── ChatGoogleGenerativeAI
  └─ chat.py SSE ──────────────────────────────── gemini.stream_chat ──── ChatGoogleGenerativeAI

YAML cases + replay fixtures
  └─ LangSmith evaluate()
        ├─ target: lesson graph (replay skips the model node)
        └─ evaluators: checks.py, plus the existing Gemini judge on a live run
```

### What this supersedes in ai-api.md

Only these two clauses, and only for an in-process Gemini chat model and an in-process graph:

- "One Gemini client implementation" / "Single Gemini SDK/HTTP client." The client implementation may be LangChain's Gemini chat model, still inside `gemini.py`, still one provider.
- "not Interactions API / managed agents." An in-process `StateGraph` is allowed. LangGraph Platform, a hosted agent server, and any managed-agent API are not.

Still in force: Gemini only, two model IDs in config, SSE mapped from streamed chunks, skill-file boundaries, text-only calls, structured lesson JSON as the curriculum contract.

### Invariants the adapter must keep

`stream_chat` and `generate_json` keep their signatures and return types.

- Keyword arguments and `ChatTurn` history stay.
- `stream_chat` yields string chunks as the model streams. It must not accumulate the full reply and yield it once.
- `generate_json` returns a JSON string.
- `on_usage` still receives `prompt_token_count`.
- Quotas in [llm_usage.py](../../../apps/backend/app/services/llm_usage.py) stay. The adapter still calls `on_usage`.

`GeminiError.code` values stay:

- `LLM_TIMEOUT`
- `LLM_QUOTA_EXCEEDED`
- `LLM_CONTEXT_LIMIT`
- `LLM_API_ERROR`
- `LLM_EMPTY_RESPONSE`
- `LLM_CONFIG_ERROR`

Mock patch paths stay:

- `app.api.v1.chat.stream_chat`
- `app.services.gemini.generate_json` (module attribute, so `mock_generate_json` keeps working)

LangChain will wrap `google.genai` errors in its own types. The adapter maps those back onto the codes above. If quota status (`RESOURCE_EXHAUSTED`) cannot be recovered, LangChain does not go into `gemini.py`. Later tasks call today's client. SSE and HTTP clients branch on these codes.

`langchain-google-genai` must not pull `google-genai` past the pin `>=1.75,<2` in [pyproject.toml](../../../apps/backend/pyproject.toml). Each library is added in the task that first uses it. Read the lockfile diff.

### What LangChain does not replace

- Skill markdown, [skills.py](../../../apps/backend/app/services/skills.py), and [prompt_assembly.py](../../../apps/backend/app/services/prompt_assembly.py).
- [extraction.py](../../../apps/backend/app/services/extraction.py). Chat is prose plus fenced JSON.
- Lesson curriculum `response_schema`. `LessonCurriculum.partner_session` is not a schema Gemini accepts, so generation stays JSON text, Pydantic, and one repair.
- Report parsing and `apply_report_ops`. The report writer already passes `response_schema=ReportOpsPayload` and validates the string in [report_writer.py](../../../apps/backend/app/services/report_writer.py).
- FastAPI, SSE event names, Postgres, auth, the listening catalog, and mistake scheduling.
- Agents, tools, and retrievers. [rag_langchain.md](../llm_improvement_20260823/rag_langchain.md) stays a separate change.

### What LangGraph does not replace

The job row, the background task, and SQL context assembly. Those stay the node bodies and the route.

The private repair copy in `evals/run.py` (`_generate_with_optional_repair`) goes away when the LangSmith target calls this graph, not by teaching the old harness to call the graph first.

### What LangSmith replaces

The harness, not the tests. These functions go away because `evaluate()` already does their job:

- `async_main` and `_run_case`
- `_markdown_summary` and the hand-written `evals/results/*.json` report
- `_maybe_judge`
- `_generate_with_optional_repair`
- `_load_baseline` and the hand-rolled new-failure diff, once a summary evaluator reads scores

What stays, because this is what we test:

- YAML cases under [evals/cases/](../../../evals/cases/), loaded into the `data` argument. They are not copied into a LangSmith cloud dataset.
- Replay fixtures. `--replay` means the target returns the frozen completion and does not call Gemini.
- [checks.py](../../../evals/checks.py). Each check is registered as an evaluator with LangSmith's `(inputs, outputs, reference_outputs)` signature. Same assertion.
- `expect_fail` on the example. The evaluator reports pass when the check outcome matches that flag.
- Judge rubrics in [evals/judges/](../../../evals/judges/). A judge is one more evaluator. It still does not fail CI. On `--replay`, a canned `.judge.json` is the evaluator result.

CI keeps this command and still needs no API key:

```bash
python -m evals.run --suite regression --replay
```

`upload_results=False` is the default. `--upload` is optional. It needs `LANGSMITH_API_KEY`, spends the Developer plan (5,000 traces per month, 14-day retention), and sends synthetic fixture text only. Inbox stubs from `evals.mine` are not uploaded. [methodology.md](../../../evals/docs/methodology.md) will say the orchestrator is `evaluate()` and the cases are still the YAML files.

## Alternatives considered

### Call LangChain from every route

Rejected. Chat, lesson generation, reports, and evals would each construct a model. The mock seams and the error taxonomy would split. `gemini.py` would remain beside a second client.

### Keep the custom eval loop and optionally call LangSmith

Rejected. That leaves the 980-line harness and adds a second pass. `evaluate()` is the loop. There is one entry point. It loads examples and calls LangSmith.

### `with_structured_output` on the report writer

Rejected. It returns a model instead of text and raises a different error on a bad payload. Lesson finish would change. Out of this migration.

### `ChatPromptTemplate` or LangSmith Hub prompts

Rejected. They do not delete prompt code. Skill files stay the prompt store.

## Consequences

- `gemini.py` is the only Gemini client. Its public functions are the framework boundary.
- Lesson generation repair exists once, in the graph, used by the job and by the eval target.
- The eval suite's pass/fail cases stay the YAML files and `checks.py`. The process exit code still comes from gated scores. Judges stay informational.
- Production does not set `LANGSMITH_TRACING`. There is no local LangSmith server (Enterprise) and no LangGraph Platform.
- If the chat move does not shrink `chat.py`, no chat graph is merged.

## Assumptions

- `ChatGoogleGenerativeAI` can stream text chunks and expose prompt-token counts close enough to map onto `on_usage` and the existing metrics. If it buffers the full reply, drops usage, or hides quota status codes, LangChain stays out of `gemini.py`. LangGraph can still call the current functions.
- One in-process graph is enough.
- `evaluate(..., upload_results=False)` runs the loop with no account. The cloud UI is only `--upload`.
- Author-labeled calibration stays informational. Judges do not fail CI.

## Not doing

- A new judge model. The current Gemini rubrics stay.
- `with_structured_output` on the report writer.
- `ChatPromptTemplate` and LangSmith Hub prompts.
- A second eval runner beside `evaluate()`.
- RAG, tools, multi-agent, or a second model provider.
- Production trace upload.
- Rewriting `chat.py` until the LangSmith target is the lesson graph and the old case loop is gone.

## Implementation order

Each step leaves the replay command green. A step that adds a concept and deletes none does not land.

### 1. LangChain inside `gemini.py`

Add `langchain-core` and `langchain-google-genai` only.

- Signatures and return types stay.
- The `GeminiError` codes above still fire, including empty JSON and a missing API key. Extend `test_gemini_errors.py` if LangChain's exception type is the new source.
- Chat SSE tests and lesson-generation tests pass with the existing fixtures and no fixture edits.
- A streamed chat still yields more than one chunk.
- `uv.lock` still constrains `google-genai` to `>=1.75,<2`. A forced major bump stops the change.
- The duplicated try/except bodies are one path. The file is not larger than today by more than the model-construction lines.

Verify with `cd apps/backend && uv run pytest`, then `python -m evals.run --suite regression --replay` from the repo root with `PYTHONPATH=apps/backend:.` and no API key.

If the streaming or error-code criteria fail, revert this step. Later steps call today's `gemini.py`.

### 2. Lesson-generation graph

Add `langgraph` only. One `StateGraph` owns generate, validate, and the single repair. The production job invokes it. Replay input is a field on graph state so the eval target can skip the model node. Do not rewrite `evals/run.py` in this step.

- Invalid JSON still gets one repair call. A second failure still fails the job.
- A `GeminiError` still fails the job with no repair call.
- `mock_generate_json` still patches `app.services.gemini.generate_json`.
- The graph module holds the branch. `lesson_generation.py` does not keep a second copy.
- The replay command still passes, unchanged, with no API key.

### 3. LangSmith replaces the eval harness

Add the `langsmith` package. `evaluate()` becomes the loop. The target calls the lesson graph, or returns the replay completion when `--replay` is set. Evaluators are the existing checks and, on a live run, the existing judge.

- `evals/run.py` no longer defines the case loop, `_run_case`, `_markdown_summary`, `_maybe_judge`, or `_generate_with_optional_repair`.
- YAML case files, replay fixtures, and `checks.py` behavior are unchanged, including `expect_fail`.
- The replay command exits 0 with no `LANGSMITH_API_KEY` and no Gemini key.
- `--upload` errors clearly when the key is missing, does not read the database, and does not upload inbox stubs.
- Judges still do not change the exit code.
- The CI workflow command stays the same.

### 4. Chat-turn graph, or stop

Move assemble, stream, extract, and persist out of `chat.py` only if the route gets shorter and the SSE tests still patch `app.api.v1.chat.stream_chat`.

- SSE event names and payload fields stay the same.
- If the move does not shrink `chat.py`, stop. No chat graph file is merged.
- Fence parsing stays in `extraction.py`.
- Onboarding and lesson remain two entry states, using the mode map in `skills.py`.

## Risks

- LangChain exception wrapping hides `RESOURCE_EXHAUSTED`. The adapter step fails closed and keeps `google-genai` if the codes cannot be recovered.
- Graph state can duplicate the lesson job's local variables. Compare the graph to the old function before touching chat.
- `--upload` sends fixture text that imitates a learner. Default is `upload_results=False`. Upload is a separate flag. Synthetic cases only.
- Replacing the harness changes the CI exit path. The LangSmith step keeps the same command and the same pass/fail cases, and deletes the old loop in that same change so two orchestrators never both exist.
