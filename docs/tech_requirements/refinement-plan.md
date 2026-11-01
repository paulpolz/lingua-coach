# Code review and refinement plan

> **Status: implemented, 2026-11-01.** A review of `apps/` against these docs and the `.cursor/rules` and `.cursor/skills` standards. PRs 0–8c are in the working tree: test foundation, F1–F7, E1, A1–A3, Part F (backend, schemas, skills), RAG stage 1 ([rag.md](./rag.md)), LangSmith code ([evals.md](./evals.md)), D1–D13, and the frontend PRs 5c and 8c. Still open: a real staging deployment and the first LangSmith experiments (need accounts), and RAG stage 2 (gated on evals).

## Context

This document covers a quality review of `apps/` against `docs/`, explanations of Pydantic + LangChain, how RAG could serve the agent's context, how LangSmith could run an evals loop, and what a standard backend test setup should look like, and ends with a refinement plan.

The review uses the project's own standards: `.cursor/rules/*.mdc` (engineering-standards, architecture-and-docs, verification, karpathy-guidelines) and `.cursor/skills/` (code-review-and-quality five-axis review and severity labels, code-simplification, api-and-interface-design, security-and-hardening's LLM section, observability).

Severity labels follow `code-review-and-quality`: **Critical** blocks merge, *(no prefix)* is Required, **Consider** is optional, **Nit** is minor.

Overall verdict: the backend is small (~2.4k LOC), consistent, well commented and closely matches the docs. Its weak points are concurrency and transactions, prompt context that grows without limit, repeated query snippets in the routers, and a thin test suite (one 412-line unittest file built on hand-rolled DB fakes).

---

## Part A — How it works today

### Pydantic (in this repo)
- **Settings**: `app/config.py` uses `pydantic-settings` `BaseSettings`. It reads env and `.env` into typed fields once, at import time, as `settings`.
- **HTTP contracts**: `app/schemas/*.py`. FastAPI uses them to validate request bodies (422 on mismatch) and to serialize responses (`response_model=`). Pydantic v2 runs on a Rust core (`pydantic-core`), so validation is fast.
- **LLM contracts**: `app/schemas/llm.py` (`OnboardingReply`, `LessonReply`, `LessonCurriculum`, `ReportPatch`). Each model does three jobs:
  1. It **generates the JSON Schema** sent to Gemini (`Model.model_json_schema()`). The `Field(description=…)` texts end up in that schema, so they are prompt text the model reads.
  2. It **validates** the model's JSON: types, `min_length`, `Literal`, and `field_validator` such as stripping `content`.
  3. It **normalizes**: with `extra="ignore"`, unknown keys are dropped, and `model_dump()` writes every key, with nulls for omitted optional fields. This is why the stored JSON always has a fixed shape.

### LangChain (in this repo, `app/services/gemini.py`, to be renamed `structured_llm.py` per D13)
- `ChatGoogleGenerativeAI` is LangChain's wrapper for Gemini. It implements the `BaseChatModel` "Runnable" interface (`invoke`, `ainvoke`, `stream`, `batch`).
- Messages: `SystemMessage` comes from the skills plus the language policy. `HumanMessage` and `AIMessage` come from `ChatTurn` history.
- `with_structured_output(Schema, method="json_schema", include_raw=True)` returns a new Runnable that does the following:
  - passes the Pydantic JSON Schema to Gemini's native structured output (`response_schema`), so the model is constrained to emit matching JSON;
  - parses the reply into a `Schema` instance;
  - with `include_raw=True`, returns `{"raw": AIMessage, "parsed": Schema|None, "parsing_error": Exception|None}` instead of raising. The code reads token usage from `raw.usage_metadata` even when parsing failed.
- Pipeline in one line: `metered_structured_call` (quota reserve in Postgres) → `generate_structured` (LangChain call + timeout + metrics + logs) → returns the Pydantic object → the router persists `model_dump()`.
- What LangChain buys here: provider abstraction, the structured-output plumbing, a uniform message format, and free LangSmith tracing (Part C). Right now only `langchain-core` and `langchain-google-genai` are in use. Agents, chains and LCEL are not, which is fine for this scope.

---

## Part B — RAG for agent context retrieval

Full proposal with diagrams and schemas: [rag.md](./rag.md).

**The current problem.** Context is either "everything" or "a fixed slice", so it grows without limit:
- Lesson generation: `services/lesson_generation.py:76` loads **all** mistakes and 5 full prior lessons.
- Report writer: `services/report_writer.py:79` sends the **full body of all 4 reports**. `update_log` and `daily_log` grow on every lesson through `append_entry`, so prompt size grows linearly with lessons. It will eventually hit `LLM_INPUT_TPM_LIMIT` (250k) and latency and cost will drift upward.
- Lesson chat: only 10 due mistakes, chosen by date rather than by relevance to today's grammar focus.

**Recommended approach, in order. Do the cheap steps first; most of the gain needs no vectors.**
1. **Structured retrieval** (no embeddings), per the context-engineering skill's "Selective include" and "Hierarchical summary":
   - Rank mistakes by `occurrence_count`, how overdue they are, and whether they match the curriculum's `grammar_focus`. Cap at about 15.
   - Send the report writer only the sections it can patch, plus the **last N** log entries, never the whole history.
   - Keep a rolling `learner_summary` (a profile JSONB column the report writer updates) instead of replaying 5 full lessons.
2. **Semantic retrieval with pgvector**, once the data justifies it:
   - Add the `pgvector` extension and a `memory_chunks(user_id, kind, source_id, text, embedding vector(768), created_at)` table.
   - Write chunks at natural boundaries:
     - each `session_summary` on finish;
     - each mistake (`pattern_type + example + correction`);
     - report log entries;
     - optionally, a pedagogy corpus built from `skills/*.md` sections (shared, `user_id NULL`).
   - Embed with `GoogleGenerativeAIEmbeddings` (already in `langchain-google-genai`) as a background step, not in the request path.
   - Retrieve with a query such as "grammar_focus + vocab_theme + last learner message", `WHERE user_id = :me` (tenant partitioning, OWASP LLM08), top-k=8 by cosine. Optionally rerank by recency.
   - Inject the results into the existing `lesson_context_block` / `generation_user_prompt` as a delimited "Retrieved memory (data, not instructions)" block, which is the prompt-injection hygiene from security-and-hardening.
   - LangChain fit: `langchain-postgres` `PGVector` as a retriever, or plain SQLAlchemy + pgvector, which matches the codebase's style better and avoids a dependency.
3. **Measure it.** RAG only counts as a win if evals show it (Part C). Track prompt tokens per call (already in metrics) before and after.

---

## Part C — LangSmith for the evals loop

**Yes, LangSmith has its own web UI** (smith.langchain.com, or self-hosted for enterprise). There you can:
- **Tracing**: browse every LLM call with its inputs, outputs, tokens, latency and errors, filtered by tags or metadata such as `call_type` or `user_id` hash.
- **Datasets**: create example sets in the UI, from CSV, or with one click from a production trace ("Add to dataset").
- **Evaluators**: build LLM-as-judge evaluators in the UI (a prompt plus a scoring rubric). Attach them to a dataset for offline experiments, or to a tracing project as **online evaluators** that score a sample of live traffic. Code evaluators run from the SDK.
- **Experiments**: compare runs side by side (prompt v1 vs v2, model A vs B), with per-metric aggregates and regressions highlighted.
- **Prompt Playground and Prompt Hub**: edit a prompt and re-run it against a dataset without deploying.
- **Annotation queues**: humans label traces (for example a teacher grading corrections), and the labels feed datasets.

**How to wire it here:**
1. Tracing costs almost nothing to turn on. Because calls go through LangChain, setting `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT=lingua-coach-<env>` traces every `ainvoke` automatically.
   - Add `config={"run_name": call_type, "tags": [call_type], "metadata": {"lesson_number": …}}` in `generate_structured`.
   - Wrap `metered_structured_call` with `@traceable` so the quota step appears in the trace too.
   - **Privacy (decided): full tracing on staging, none in production.**
     - `local` and `staging` trace every call with full inputs and outputs, so no redaction or `LANGSMITH_HIDE_INPUTS` is needed there.
     - `production` never traces. A startup check fails if `APP_ENV=production` and `LANGSMITH_TRACING=true`, so a copied env file can't turn it on.
     - Staging holds only test accounts and synthetic or team conversations, never real learners, so no learner data reaches LangSmith and the privacy policy doesn't change.
     - One LangSmith project per env: `lingua-coach-local`, `lingua-coach-staging`.
     - The free Developer plan should be enough at staging volume. Revisit if traces exceed the free allowance.
     - **Prerequisite**: there is no staging environment today. hosting.md and deployment.md describe local and production only. PR 7 adds a staging deployment (own DB, Clerk dev instance with `CLERK_JWT_ISSUER` set, per F1) and documents it.
2. Offline eval suite in `apps/backend/evals/`:
   - Datasets per call type: `onboarding_turns`, `lesson_turns`, `curriculum_gen`, `report_patch`. Seed each with about 20–50 hand-written inputs (system instruction inputs and history), plus examples promoted from real traces.
   - Deterministic evaluators in code:
     - the schema parsed;
     - `LessonCurriculum` has no speaking slots and no URLs;
     - every `ReportOp.section_id` exists in the current report;
     - the reply language matches the target (a langdetect-style heuristic);
     - `suggest_finish` is false while slots are open;
     - corrections' `span` appears in the learner message.
   - LLM-as-judge evaluators, defined in the UI so non-engineers can tune them:
     - pedagogy quality against `exercise_tutor.md`;
     - correction accuracy;
     - tone and level appropriateness;
     - onboarding asks one question per turn.
   - Runner: `langsmith.aevaluate(target=generate_structured-wrapper, data="lesson_turns", evaluators=[…], experiment_prefix=git_sha)`.
3. The loop: staging traces (from QA sessions, demo runs and replayed eval inputs) → the online evaluator flags low scores → an annotation queue → fix the skill markdown or a schema description → run the offline experiment → compare in the UI → merge.
   - CI: a nightly or manual `workflow_dispatch` job runs `evals/` against real Gemini and fails when scores drop more than a threshold. It is never part of the PR gate, because it is nondeterministic and costs money.

---

## Part D — Standard backend testing framework

Today there is a single `unittest` module with a `MemoryDB` fake that re-implements SQLAlchemy behavior. It can't catch real-database bugs like F3 and F4 below.

**Target stack**:
- **Packages**: `pytest`, `pytest-asyncio`, `httpx` (already a dep), `asgi-lifespan` (optional), `pytest-cov`, `ruff`, `mypy`. Add them as `[dependency-groups] dev` in `pyproject.toml`.
- **Real Postgres**: either the CI `services: postgres:16` container or `testcontainers[postgres]`.
- **Generic fake model**: `langchain_core.language_models.fake_chat_models` (`GenericFakeChatModel`), or a single fixture that patches `generate_structured` (`app.services.gemini` today, `app.services.structured_llm` after the D13 rename in PR 8a).

```
apps/backend/tests/
  conftest.py            # engine on test DB, alembic upgrade head once per session,
                         # per-test transaction + rollback (SAVEPOINT), app.dependency_overrides[get_db],
                         # auth override (get_current_principal -> fixed ClerkPrincipal),
                         # `fake_llm` fixture: queue of Pydantic replies or LLMError per call
  factories.py           # make_user / make_profile / make_lesson(status=…) / make_plan
  unit/                  # pure functions, no DB
    test_report_ops.py  test_pace.py  test_skills.py  test_prompt_assembly.py  test_llm_schemas.py
  integration/           # services against real Postgres
    test_llm_usage_limits.py  test_lesson_generation_job.py  test_report_writer.py
  api/                   # httpx.AsyncClient(transport=ASGITransport(app)) end-to-end per router
    test_auth.py  test_chat_onboarding.py  test_chat_lesson.py  test_onboarding_accept.py
    test_lessons_lifecycle.py  test_progress_profile.py  test_errors.py
  contract/              # snapshot of app.openapi() and of each LLM schema's JSON schema
evals/                   # LangSmith, marked @pytest.mark.eval, excluded from default run
```

**Conventions** (verification.mdc):
- Tests are deterministic and never call Gemini.
- Every bug fix gets a regression test that fails first.
- Test names describe behavior, e.g. `test_finish_past_pace_window_slips_plan`.
- Test the error paths: 409, 429 with `Retry-After`, 502/504 mapping, and `PERSIST_FAILED`.
- Parametrize the `LLMError` → HTTP table.

**CI** (`.github/workflows/ci.yml`): rename `backend-import` to `backend-check`, add a postgres service, and run `ruff check`, `ruff format --check`, `mypy app`, then `pytest -m "not eval" --cov=app --cov-fail-under=70`.

---

## Part E — Review findings (verified in code)

### Correctness / concurrency

- **F1 · Critical (security): any Clerk dev instance can authenticate.** `core/clerk_auth.py` `_is_allowed_issuer`: when `CLERK_JWT_ISSUER` is unset, *any* `https://*.clerk.accounts.dev` issuer is trusted. Anyone can create a free Clerk dev app, mint tokens, sync a user and consume your Gemini quota.
  - Fix: require `CLERK_JWT_ISSUER` whenever `app_env != "local"`, failing at startup.
  - Also check `azp` against `cors_origins`.
- **F2: lesson start race → 500.** `api/v1/lessons.py:83-113` checks for an active lesson and then inserts. Two concurrent starts both pass the check and compute the same `max+1`, so the unique `(user_id, lesson_number)` constraint fails and the user gets `INTERNAL_ERROR`.
  - Docs (database.md) admit the rule is "enforced in the app".
  - Fix: make `ix_lessons_user_id_active` a **unique** partial index (migration), catch `IntegrityError`, and return `409 ACTIVE_LESSON_EXISTS`.
- **F3: duplicate mistakes within one turn.** `AsyncSessionLocal(autoflush=False)` (`db/session.py:12`). In `chat.py:_upsert_mistake`, if one `LessonReply.mistakes` list holds the same `pattern_type` twice, the second `select` doesn't see the unflushed first row and inserts a duplicate. Later `scalar_one_or_none()` then raises `MultipleResultsFound`, which turns every later chat turn into a 500.
  - There is no DB unique constraint on `(user_id, pattern_type)`.
  - Fix: add a unique constraint, dedupe by `pattern_type` before the loop, and use `INSERT … ON CONFLICT DO UPDATE`.
- **F4: stuck lessons after restart.** `BackgroundTasks` runs inside the web process. A deploy or crash during generation leaves the job `running` and the lesson `generating` forever, and then `/lessons/start` returns 409 permanently.
  - Fix, the simplest version: in `_active_lesson`, treat `generating` older than `gemini_timeout_seconds × 2` (`llm_timeout_seconds` after D13) as failed (mark it and continue).
  - A later option is a real queue (arq or Postgres `SKIP LOCKED`), but per engineering-standards, don't add it speculatively.
- **F5: finish holds a DB transaction open during an LLM call.** `finish_lesson` → `update_reports_after_lesson` makes a Gemini call of up to 120s inside the request's open transaction, with row locks and a pooled connection held.
  - Fix: commit the finish first, then run the report update as a background task in its own session, as lesson generation already does.
  - This also makes finish fast for the user. Update backend.md's finish flowchart.
- **F6: onboarding accept trusts a client-supplied roadmap.** `schemas/onboarding.py`: `course_roadmap: dict` is stored and later fed into prompts without validation, which crosses a trust boundary (security skill, OWASP LLM01).
  - Fix: type it as `CourseRoadmap` and store `model_dump()`.
- **F7: the report-writer context grows without limit.** See Part B. It is required eventually, but only matters as lessons accumulate.

### Efficiency

- **E1: rate checks run several queries per call.** `reserve_gemini_call` (`reserve_llm_call` after D13) runs 2 aggregate queries and `check_and_record_user_limit` runs another. Merge the minute and day windows into one query with `count(*) FILTER (WHERE created_at >= :minute)`, which saves a round trip per LLM call.
  - Separately, the check-then-insert is not atomic across processes. That is acceptable for soft limits; document it.
- **E2: see F5.** Moving the report call out of the request is the largest latency win.
- **E3: lesson generation loads all mistakes** with no limit (`lesson_generation.py:76-78`). Cap and rank them (Part B, step 1).

### Docs alignment

- **A1: every code link in `docs/tech_requirements/*.md` is broken.** They use `../../../../apps/...`, which resolves outside the repo; the correct prefix is `../../apps/...`.
- **A2: the product says reading and writing only, but the progress report has a "Listening" row.** The lesson prompt says "Reading and writing only" and the latest commit removed the listening catalog, yet `report_seed.blank_progress_markdown` and `cjm.md:114` still list Listening. **Decided: Listening is out.** Remove it from both, along with the Listening row in `report_writer.md` (PR 5b).
- **A3: docs to update after F2–F6** (unique index, background report update, typed accept body):
  - database.md (indexes and migrations list);
  - backend.md (finish flow, accept validation);
  - deployment.md (CI jobs).
- Everything else checked matches the docs: endpoints, error codes, limits, metadata keys, call types and context per call.

---

## Part F — Time-boxed lessons and simpler skills

### Goal

A lesson lasts about as long as the learner said at onboarding (`time_budget.minutes_per_session`). If they asked for 15 minutes a day, the lesson is about 15 minutes of practice.

Today the lesson is a checklist of slots (warm-up, grammar, vocabulary, reading, writing, goal-specific, review). When the learner answers fast or skips a slot, the checklist runs out and the lesson ends early. The fix: the **time budget** sets the lesson length, not a slot list. The tutor keeps practicing until the time is used.

### Why we can drop the activity split

Every exercise in this product works the same way: the tutor writes something, the learner types an answer. A grammar drill, a vocabulary drill, a reading question and a writing task are all the same chat exchange. So the split into blocks costs prompt tokens, schema fields and UI without changing what the learner does.

Each lesson still covers the same **aspects**: new grammar, new vocabulary, review of past mistakes, and reading/writing in the context of the learner's goal. They are mixed inside one conversation instead of shown as separate blocks.

### How time is measured (backend, deterministic)

The LLM can't measure time, so the backend measures it and tells the tutor every turn.

- **Active minutes**: the sum of gaps between consecutive messages in the lesson chat, with each gap capped at `settings.lesson_idle_cap_minutes` (default 5). A learner who leaves the tab for an hour adds 5 minutes, not 60. This differs from `started_at`, which is set when generation finishes and keeps running through stops. The pace clock keeps using `started_at` as it does now.
- **Target minutes**: `profile.time_budget.minutes_per_session`, copied into `lessons.payload.target_minutes` when the lesson is generated. A plan change in the middle of a lesson then doesn't move the goal. **No default.** The learner has to give a lesson length at onboarding:
  - the interviewer doesn't hand off until it is known;
  - accept rejects a profile without it with `422 TIME_BUDGET_REQUIRED`;
  - `/lessons/start` returns `409 TIME_BUDGET_REQUIRED` for a legacy profile without it. The dashboard then asks for the minutes, and `PATCH /profile` saves them.
- **Each turn**: `lesson_context_block` adds `Time: {active} of {target} min used.` The turn metadata returns `{active_minutes, target_minutes}`, re-measured right before the reply is saved (including the learner's message), so the UI shows what finish will record.
- **Guard**: the backend sets `suggest_finish` to false while `active_minutes < target_minutes - 1`, whatever the model says. The skill starts the recap about 2 minutes before the target and sets `suggest_finish` once the Time line shows at least `target - 1`; the guard makes sure of it.
- **Finish**: `session_summary.duration_minutes` becomes active minutes, computed before the chat rows are deleted, plus `target_minutes`. The learner can still finish early with the Finish button (product rule). The dialog shows "You practiced 8 of 15 min".
- **Early finish (decided)**: it still counts as an accomplished plan day, and pace works as now. The summary records the shortfall as `shortfall_minutes = max(target - active, 0)` and `finished_early = shortfall_minutes > 1` (the guard's tolerance). The report writer mentions it in `latest_session`. The shortfall never blocks or undoes the finish.

### Skill changes

#### `exercise_tutor.md` (rewrite, about half its current length)

**Remove** (the code already does this or the model never does it):
- the `Inputs` YAML, since `prompt_assembly.py` builds the context;
- the "Context retrieval and persistence" table and "What to persist";
- the `lessons.payload` JSON example, since `LessonCurriculum` and its `Field` descriptions are the contract;
- the mistake JSON example, since `MistakeEntry` covers it;
- the whole `session_summary` section. **The backend builds it in `lessons.py:_session_summary`, the model never writes it.** Today the skill asks for fields like `performance_notes` and `focus_pattern_result` that nothing produces.
- "Lesson agenda (chat + pinned checklist)", slot mapping, "Completion and exit criteria";
- "Partner session pack";
- the pointer to `vocabulary_practice_formats.md` (see below).

**Add:**
1. **Time budget.** The lesson lasts `target_minutes`. Read the `Time:` line each turn.
   - Before the end: if the planned material is done, keep practicing. Use a harder variant, a new context, another round on a due mistake, or reuse today's words in a short writing task.
   - Never wrap up early because the learner was fast.
   - Last ~2 minutes: a short recap (what went well, what to watch), then `suggest_finish`.
2. **Skips.** If the learner skips or gives a minimal answer, don't move on to new material. Offer an easier or shorter version of the same item, or switch the angle (another context, multiple choice, or fill in the blank). A skip doesn't shorten the lesson.
3. **Teach, then practice**, for each aspect:
   - **Grammar**: a short explanation (rule, 2 examples, a typical mistake, a contrast with a structure they know), then 3–5 graded exercises: recognize → transform → fill in the blank → produce freely → use in a goal-context paragraph.
   - **Vocabulary**: 6–10 items in the full format (meaning, collocations, example, prompt to use it), then exercises: match the meaning, gap-fill, paraphrase without the word, word families, a collocation choice, and using 2–3 of the words in their own text.
   - **Review**: retest due mistakes in a new context before teaching new material, and once more near the end.
   - **Reading/writing**: a short passage or a real-format writing task (email, message, summary) where the new grammar and words have to appear.
4. **Repertoire**: one list of exercise formats that all work in chat: gap-fill, transformation, error-spotting in the tutor's sentence, translation-free paraphrase, sentence building from given words, mini-dialogue written by the learner, rewrite in another register, "defend the opposite view", describe-without-saying-the-word, and Format A/B ideas from `vocabulary_practice_formats.md` turned into solo chat drills. Rotate formats within the lesson so it doesn't turn into the same drill.
5. **Feedback loop**:
   - When an item is done correctly, especially without help, **praise it specifically** ("past perfect used correctly twice, no hints") and report it in `practiced` as `solid`.
   - When it is wrong: correct it with a one-line rule, re-elicit it once, report it in `mistakes` as now, and mark it in `practiced` as `shaky`.
   - Due mistakes that come out right again are reported `solid`. The streak moves at most once per lesson, so a pattern closes after solid results in two different lessons; `shaky` resets it.
6. Keep: the language rules, the core coaching rules, the anti-patterns (drop the slot-related ones).

#### `course_composer.md`

- **Step 3 "weekly template"**: drop the 7-activity % table and the `activities` list. Replace them with one rule: each lesson is `minutes_per_session` of mixed chat practice (new grammar, new vocabulary, mistake review, goal-context reading/writing). The weekly template becomes `minutes_per_session`, `sessions_per_week` and `weekends`.
- **Step 4 first block**: the day table is reduced to `grammar_focus | vocab_theme | goal_context`. Drop `input_type`, `production_focus` and `goal_specific_focus`.
- **Chat presentation**: replace "Your weekly rhythm | Activity | Minutes" with one line: "Each lesson: ~N minutes of chat practice mixing grammar, vocabulary and writing for your goal; past mistakes come back until they stick."
- **Remove** (duplicates code or schema):
  - the "Flow" diagram;
  - the whole `course_roadmap` JSON example and "Field notes";
  - "Acceptance" steps 1–6, which describe `onboarding.py`, not the model's job, and also contain a stray `aOn` typo;
  - "Optional partner (out of app)".
  - What to keep from the example and field notes moves into `Field(description=…)` on the `CourseRoadmap*` models. Gemini reads those as part of the schema. Examples: "themes only, no word lists or URLs" and "string values in the target language, keys in English".
- **Keep**: Steps 1, 2, 5 and 6, the language rules, and the rule "emit `course_roadmap` on a revised plan, null on a clarifying question" (one line, since the schema description says the same).
- Steps 1–2 may still say "writing-heavy goals need more days", because that is about plan length, not lesson shape.

#### `onboarding_interviewer.md`

- **Remove** the `learner_profile` YAML. `LearnerProfile` is the contract. Move the two field notes worth keeping ("concrete real-world outcome", "observable behaviors, not CEFR labels") into `Field` descriptions.
- **Cluster 3 (time)**: ask for a concrete number of minutes per lesson and say that this is how long each lesson will run. Don't hand off to `course_composer` until `time_budget.minutes_per_session` is known. There is no default; if the answer is vague ("a bit", "when I can"), ask again for a number. Add `minutes_per_session: int | None = Field(ge=5, le=180, description="Length of one lesson in minutes; every lesson is timed to this. Required before a roadmap is drafted.")`. `CourseRoadmapWeeklyTemplate.minutes_per_session` stays required.
- Drop the practice-partner question, `optional_partner_minutes` and `PracticePartner`. They aren't needed in a product with no speaking (D9, decided).

#### `vocabulary_practice_formats.md`

- It is built for **partner speaking** ("partner guesses", "argue 2 min"). It is also loaded through `should_include_vocab_formats`, which matches slot ids, and slots are being removed.
- Recommendation: fold the formats that work in chat into the exercise_tutor repertoire (item 4 above), delete the file, and delete `should_include_vocab_formats` and its `include_vocab` plumbing in `skills.py` and `prompt_assembly.py`.

#### `report_writer.md`

- The input now includes `active_minutes` / `target_minutes` and the `practiced` results (solid and shaky items). `latest_session` should report time practiced vs target, what's now solid (praise), and what's still shaky.
- A2 (decided, out): remove the Listening row from the default categories (and from `report_seed.blank_progress_markdown`).
- The `four_week_plan` description becomes "grammar / vocabulary / goal-context focus per day".
- Section-id table: keep it. The model needs the ids and the "typical op" hint, and the code doesn't send that hint.

#### `skills/README.md`

- Drop the `vocabulary_practice_formats` row. Change the principle "Fixed ritual, personalized content" to "Fixed time budget, personalized content".
- Fix the broken `../../../docs/mvp/init/...` links (same class as A1).

### Rule for "what stays in a skill"

A skill says **how to teach and decide**. It doesn't repeat:
- **payload shapes**: the Pydantic model, its `Field(description=…)` text and `model_json_schema()` already send them to Gemini on every call;
- **persistence steps**: routers and services;
- **context lists**: `prompt_assembly.py`.

If a constraint matters to the model ("null on a clarifying question", "themes only, no URLs"), it goes into the `Field` description so it sits next to the field it constrains. The contract snapshot tests (Part D, `contract/`) then catch drift. Expected result: the skills shrink from ~930 to ~500 lines, with fewer prompt tokens on every lesson call.

### Code changes

**Backend**

| File | Change |
| --- | --- |
| `schemas/llm.py` | `LessonCurriculum`: drop `slots`, `input_task`, `goal_specific_task`, `partner_session` (resolves D9) and `CurriculumSlot`/`InputTask`/`GoalSpecificTask`. Keep `lesson_goal`, `grammar_focus`, `vocab_theme`, `milestone_index`. Add `new_vocabulary: list[str]` (6–10 items, for review in later lessons), `review_patterns: list[str]` (due mistake types to retest) and `goal_context: str`. Rename `exit_criteria` → `practice_targets`, kept for praise and checks, not completion. |
| `schemas/llm.py` | `LessonReply`: drop `lesson_plan`, `completed_task_ids`, `LessonPlan`, `LessonPlanTask`. Add `practiced: list[PracticeResult]` with `aspect: Literal["grammar","vocabulary","review"]`, `item: str`, `result: Literal["solid","shaky"]`. Change the `suggest_finish` description to "only in the closing recap, once the time budget is used". |
| `schemas/llm.py` | `CourseRoadmapWeeklyTemplate`: drop `activities` and `partner_session`, add `sessions_per_week`. `CourseRoadmapThemeDay`: keep `grammar_focus` and `vocab_theme`, add `goal_context`, drop the other three. Delete `CourseRoadmapActivity`. Move the field notes from the skills into `Field` descriptions. `TimeBudget.minutes_per_session` gets bounds and a description. |
| `config.py` | Add `lesson_idle_cap_minutes = 5`. This is an internal measurement constant, not a lesson length. There is no default lesson length. |
| `services/lesson_timing.py` (new) | `active_minutes(db, session_id, idle_cap)` from `chat_messages.created_at`, and `target_minutes(profile)`, which raises `TIME_BUDGET_REQUIRED` when it is unset. These are pure functions plus one query, unit-tested. |
| `services/lesson_generation.py` | Store `payload.target_minutes`. Add the time budget to the generation context so the curriculum fits it: about 1 grammar point and 3–4 words in 10 min, more in 60. |
| `services/prompt_assembly.py` | `lesson_context_block` gets `active_minutes`/`target_minutes` and adds the `Time:` line. Update `generation_user_prompt` wording (no slots). Remove `include_vocab`. |
| `services/skills.py` | Remove `should_include_vocab_formats`, `_VOCAB_REVIEW_MARKERS` and the `vocabulary_practice_formats` append. |
| `api/v1/chat.py` | `_persist_turn`: compute active minutes and apply the `suggest_finish` guard. Metadata drops `lesson_plan`/`task_update` and adds `timing: {active_minutes, target_minutes}` (do this with D7 `TurnMetadata`). Apply `practiced`: a `solid` result on an existing mistake pattern pushes `next_review_at` out one step, or closes it after 2 solid results in a row. A `solid` result on grammar merges into `profile.grammar_mastery`. |
| `api/v1/lessons.py` | `_session_summary`: drop `completed_slots`, `deferred_items` and `exit_criteria_met`. Add `duration_minutes` (active), `target_minutes`, `shortfall_minutes`, `finished_early`, `practiced_solid`, `practiced_shaky`, `resolved_pattern_types` and `new_vocabulary`. `FinishLessonRequest.completed_slot_ids` is removed. |
| `api/v1/onboarding.py`, `api/v1/lessons.py` | Accept: 422 `TIME_BUDGET_REQUIRED` without `minutes_per_session`. Start: 409 `TIME_BUDGET_REQUIRED` for legacy profiles. |
| `schemas/llm.py` | Remove `PracticePartner`, `LearnerConstraints.practice_partner` and `TimeBudget.optional_partner_minutes` (D9). |
| `services/report_writer.py`, `report_seed.py` | Pass the new summary fields. Seed the four-week plan from the new theme fields and the weekly template without `activities`. Remove the Listening row. |
| Data | **No migration.** Payloads are JSONB, but existing rows hold the old shapes. Readers use `.get()` with defaults. An active lesson that still has `slots` keeps working, because the slot fields are simply ignored. `learning_plans.roadmap` from before the change keeps `activities`; `extra="ignore"` drops it on read. |

**Frontend**

| File | Change |
| --- | --- |
| `app/lesson/[lessonId]/LessonChecklist.tsx` | Replace it with `LessonTimeCard` in the same right-hand slot: "**8 / 15 min**" plus a thin progress bar. It is updated from `metadata.timing` on every turn, not a ticking timer. |
| `app/lesson/[lessonId]/LessonChat.tsx` | Remove the checklist state (`checklistTasks`, `completedTaskIds`, its ref) and `applyChecklistMetadata`. Restore `timing` from the latest assistant message on reload. Drop the `Grammar: … / Vocab: …` focus parts in the header (lines ~435). Stop sending `completed_slot_ids`. |
| `lib/chat.ts` | Remove `LessonPlan`, `LessonPlanTask`, `TaskUpdate` and `applyChecklistMetadata`. Add `timing?: {active_minutes, target_minutes}` to the turn metadata type. |
| `lib/lessons.ts` | Update the `LessonCurriculum` and `LessonSessionSummary` types. Remove `completed_slot_ids` from `FinishLessonRequest`. |
| `components/FinishLessonDialog.tsx` | Replace "unfinished slots count as 0%" with "You practiced X of Y min", and add an "early finish" variant of the text when X < Y: "It still counts; we'll note the X min you missed." |
| `app/dashboard/DashboardClient.tsx` | For a `TIME_BUDGET_REQUIRED` start error, show an inline "How many minutes per lesson?" prompt that saves through `PATCH /profile`, then retries the start. |
| `app/onboarding/PlanSummaryCard.tsx` | Replace the `activities` line with "N min per lesson · M days/week". |
| `app/dashboard/DashboardClient.tsx` | Optional: the active-lesson card shows `Grammar:` / `Vocab:` (~line 455). Keep it as a preview, or align it with the lesson header. |

**Docs**: ai-api.md (the `LessonReply` and `LessonCurriculum` rows), backend.md (metadata keys, the finish summary, the generation job), database.md (the payload example and the metadata keys), frontend.md (checklist → time card, the finish body), cjm.md (lesson shape).

---

## Part G — Duplication and code quality

This cleanup goes last, after the skills refinement in Part F. Part F rewrites the same schemas, prompt assembly and lesson chat. If the cleanup ran first, that code would be refactored twice.

Two items are already handled by Part F:
- **D7** ships in PR 5a, because that PR adds the `timing` metadata key anyway.
- **D9** is resolved there (decided): `partner_session` and the other partner fields are dropped.

### Backend (code-simplification: same output for every input)

- **D1: `select(Profile).where(Profile.user_id==…)` is repeated in 7 places.** chat (twice through `_profile`), lessons (twice), onboarding, progress, profile, plus lesson_generation. Add `get_profile(db, user_id)` in a small `app/services/queries.py`. That file also takes:
  - `active_lesson(db, user_id)`: 3 copies (lessons.py:34, progress.py:38, profile.py:29);
  - `accomplished_count(db, user_id)`: 4 copies (lessons.py:66, progress.py:29, profile.py:26, chat.py:232);
  - `last_accomplished(db, user_id)`: 2 copies.
- **D2: `/progress` and `/profile` compute the same pace snapshot.** Extract `pace_snapshot(db, user) -> (profile, done, active, last, summary)` into `services/pace.py`, which leaves both routers thin (architecture-and-docs.mdc).
- **D3: projection math is open-coded twice.** `chat.py:237` and `onboarding.py:77` duplicate `pace.compute_projected_completion`. Reuse the helper.
- **D4: hardcoded pace-window fallbacks.** The fallback `or 24` appears in pace.py:40, progress.py:51 and onboarding.py:77, while lessons.py:205 uses `settings.pace_window_hours`. Pick one, `settings.pace_window_hours`, through a `pace_window(profile)` helper.
- **D5: four copies of UUID parse + ownership check.** `_uuid_or_404` / `_owned_*` appear in chat.py, lessons.py, jobs.py and onboarding.py. Move one `get_owned(db, Model, id_str, user_id, what)` to `api/deps.py`.
  - **Decided: 422.** Type path params as `uuid.UUID`, so FastAPI rejects malformed ids with 422 before the handler runs. `get_owned` then takes a `uuid.UUID` and only returns 404 for well-formed ids that don't exist or belong to another user. Drop `_uuid_or_404`.
  - This is an API contract change. Update backend.md's error table and add an `api/test_errors.py` case. Check that the frontend treats 422 on these routes like 404 ("not found"), since today it only expects 404.
- **D6: two strip helpers in `schemas/llm.py`.** `_Reply._strip_content` and `_strip_string` + `_strip_language` do the same thing. Replace them with `Stripped = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]`.
- **D7: the seven-key chat metadata is built by hand in two branches** (`chat.py:_persist_turn`). Introduce a `TurnMetadata` Pydantic model with defaults, so each branch sets only what differs, and type `ChatTurnResponse.metadata: TurnMetadata`. This makes the documented "always seven keys" invariant hold by construction, and the frontend can share the type through OpenAPI.
- **D8: a round trip through dicts in `_save_learner_profile`.** It does `model_dump()` and then `.get()` with `or {}`. Use the typed model attributes directly. The language `.strip()` there is redundant because the validator already strips.
- **D9: `partner_session` is an always-null field.** It sits on `LessonCurriculum` and `CourseRoadmapWeeklyTemplate`, costs schema tokens on every call, and invites hallucination. **Decided: drop it, since it's not needed.**
  - Drop it together with the practice-partner profile fields (`PracticePartner`, `optional_partner_minutes`).
  - This is done in PR 5b, as part of the schema slimming.
  - Update ai-api.md, backend.md and database.md, which describe it.
- **D10 · Nit: inconsistent loggers.** `lesson_generation.py` and `report_writer.py` use `logging.getLogger`, while the rest use `core.logging.get_logger`.
- **D11 · Nit: odd `_retry_after` signature.** Its `fixed=` parameter just returns the constant. Inline 60.
- **D12 · Consider: cache `_model()`.** It builds a new `ChatGoogleGenerativeAI` on every call. Cache per `model_id` with `functools.cache`.
  - The double timeout (client `timeout` plus `asyncio.timeout`) is harmless. Keep one and say why in a comment.
- **D13: `services/gemini.py` is named after the vendor, not the job.** The module's purpose is "make one structured-output LLM call": build messages from `ChatTurn` history, call `with_structured_output`, enforce the timeout, record metrics and logs, map failures to error codes, and return a validated Pydantic object. Only `_model()` is Gemini-specific. The vendor name leaks into every caller (`chat.py`, `llm_usage.py`, `lesson_generation.py`, `report_writer.py`, tests) and would be wrong the day a second provider or `rag.md`'s `embeddings.py` sits next to it.
  - **Decided: rename everything to provider-agnostic names**, including env vars and settings:

    | Today | After |
    | --- | --- |
    | `services/gemini.py` | `services/structured_llm.py` (public API stays `generate_structured`, `ChatTurn`) |
    | `GeminiError` | `LLMError` (codes unchanged) |
    | `_model()` | `_chat_model()`, the single provider seam |
    | `GeminiCallType`, `_GEMINI_CALL_TYPES` | `LLMCallType`, `_LLM_CALL_TYPES` |
    | `reserve_gemini_call` | `reserve_llm_call` |
    | `_GEMINI_STATUS` (chat.py) | `_LLM_STATUS` |
    | `settings.gemini_api_key` / `GEMINI_API_KEY` | `settings.llm_api_key` / `LLM_API_KEY` |
    | `settings.gemini_model_chat` / `GEMINI_MODEL_CHAT` | `settings.llm_model_chat` / `LLM_MODEL_CHAT` |
    | `settings.gemini_model_lesson` / `GEMINI_MODEL_LESSON` | `settings.llm_model_lesson` / `LLM_MODEL_LESSON` |
    | `settings.gemini_timeout_seconds` / `GEMINI_TIMEOUT_SECONDS` | `settings.llm_timeout_seconds` / `LLM_TIMEOUT_SECONDS` |
    | test helper `patched_gemini` | `patched_llm` |

  - Env vars are a deployment contract, so roll them over with no downtime:
    - for one release, each setting reads both names (`validation_alias=AliasChoices("LLM_API_KEY", "GEMINI_API_KEY")`) and logs a deprecation warning when the old name is used;
    - update `.env.example`, CI and the hosting secrets (deployment.md, hosting.md);
    - drop the aliases in the next release.
  - Add `LLM_PROVIDER=google` (only `google` is valid today), so the provider is named in config rather than in identifiers.
  - Prose that describes the actual provider ("Gemini via `langchain-google-genai`") stays. Only identifiers become agnostic.
  - Update the module docstring to describe the purpose ("one structured-output LLM call: one schema, one parse, no repair call; provider: Gemini via `langchain-google-genai`").
  - Update importers, the test patch target (`app.services.gemini.ChatGoogleGenerativeAI`), and every doc that names Gemini identifiers or env vars: ai-api.md, backend.md (file tree), deployment.md, hosting.md, frontend.md, README.md, rag.md and this plan.
  - Pure rename, no behavior change. Don't add a provider abstraction layer: LangChain's `BaseChatModel` already is one.

### Frontend (scanned, not deeply reviewed)

- **FE1: the same fetch boilerplate is repeated about 12 times** across `lib/*.ts` (`apiFetch` → `if (!ok) throw toApiError` → `json()`). Add `apiJson<T>(path, token, init, fallbackMsg)` in `lib/api.ts`.
- **FE2: the two chat components duplicate their send logic.** `OnboardingChat.tsx` (381 lines) and `LessonChat.tsx` (513 lines) both have send, retry and error state (`isSending`, `sendError`, `lastFailedContent`). Extract a `useChatTurn(sessionId)` hook. `DashboardClient.tsx` (488 lines) should be split by section. This is the frontend-ui-engineering "giant components" rule.
- Rendering is safe: `react-markdown` runs without `rehype-raw`, so LLM markdown can't inject HTML.

---

## Part H — Refinement plan (small, separately reviewable PRs, ~100–300 lines each)

Every PR follows the same rule: write a failing regression test first, then the fix, then update docs.

0. **Test foundation** (prerequisite)
   - Add the pytest + Postgres harness, factories, `fake_llm` fixture, ruff and mypy.
   - Port `test_structured_output.py` cases into `api/` and `unit/`, keeping every assertion.
   - Update CI.
   - The `fake_llm` fixture patches `generate_structured` through one constant patch target. The D13 rename in PR 8a then changes only that constant.
1. **Security**: F1 (require the issuer outside local), plus a stop to echoing raw Gemini exception text in 502 bodies (log it, return a generic detail). Also A1 (broken doc links), because it's trivial.
2. **Data integrity**: F2 and F3 via one Alembic migration (unique partial active-lesson index, unique `(user_id, pattern_type)` with a dedupe step for existing rows), plus the `IntegrityError` → 409 mapping and mistake upsert via `ON CONFLICT`.
3. **Lifecycle robustness**: F4 (stale generating reaper), then F5 (report update as a background task).
4. **Trust boundary**: F6 (`CourseRoadmap` body).
5. **Time-boxed lessons and skills refinement (Part F)**, in three PRs:
   - **5a, backend timing**: `lesson_timing.py`, `target_minutes` in the payload, the `Time:` context line, the `suggest_finish` guard, and active-minutes `duration_minutes`. Adds `metadata.timing` through D7 `TurnMetadata`, which is introduced here. It is additive, so the checklist still works.
   - **5b, schema + skills**:
     - the slimmer `LessonCurriculum` / `LessonReply` / `CourseRoadmap*` and the `practiced` loop;
     - the rewritten `exercise_tutor.md` / `course_composer.md` and the trimmed `onboarding_interviewer.md` / `report_writer.md`;
     - deleting `vocabulary_practice_formats.md` and `should_include_vocab_formats`;
     - D9 (`partner_session` dropped) and A2 (Listening row removed).
     - Contract snapshots get updated on purpose.
   - **5c, frontend**: `LessonTimeCard` replaces `LessonChecklist`, plus the finish dialog text, `PlanSummaryCard`, and the type cleanup. 5b and 5c ship together, or 5c first while it still accepts the old metadata keys.
6. **Context budgeting (RAG step 1)**: F7 and E3, with ranked and capped mistakes and only the last-N report log entries sent. Record prompt-token deltas.
7. **LangSmith**: a staging deployment, tracing on in `local`/`staging` only with the production startup guard, metadata in `generate_structured`, the `evals/` package with datasets, deterministic evaluators and the `aevaluate` runner, and a nightly workflow. Docs: new `docs/tech_requirements/evals.md`.
8. **Duplication and code quality (Part G)**, last, on top of the code Part F already changed. Behavior stays identical; the PR-0 API tests and the PR-7 evals guarantee it.
   - **8a, rename**: D13. All Gemini-named identifiers, settings and env vars get agnostic names, with the env aliases kept for one release. Update `.env.example`, CI, hosting secrets and the docs. It's a separate PR, with the alias removal as a follow-up.
   - **8b, backend dedup**:
     - D1–D5 (`services/queries.py`, `pace_snapshot`, `get_owned`, `uuid.UUID` path params → 422);
     - D6 and D8 (schema cleanup);
     - D10–D12 and E1.
   - **8c, frontend**: FE1 (`apiJson`) and FE2 (`useChatTurn`, split `DashboardClient`).

**Later, data-driven:** pgvector RAG step 2, only if the evals from PR 7 show the selective-context version missing relevant history.

Decisions made (2026-11-01):
- **A2**: Listening is out (PR 5b).
- **D5**: malformed ids → 422 through `uuid.UUID` path params (PR 8b).
- **D9**: drop `partner_session` and the practice-partner fields (PR 5b).
- **D13**: rename everything to agnostic names, env vars and settings included, with one release of aliases (PR 8a).
- **Part F, early finish**: it counts as an accomplished plan day, and the shortfall is recorded (`shortfall_minutes`, `finished_early`).
- **Part F, idle cap**: 5 min per message gap (`lesson_idle_cap_minutes = 5`).
- **Part F, lesson length**: no default. The learner must provide minutes per lesson. Onboarding requires it, and legacy profiles are asked before the next start.
- **PR 7, LangSmith**: full tracing on staging (and local), never in production. Staging has no real learner data.

No open decisions remain.

## Verification

- `cd apps/backend && uv run ruff check . && uv run mypy app && uv run pytest -m "not eval" --cov=app` passes after every PR. The ported structured-output cases stay green.
- Regression tests that must fail before their fix:
  - concurrent `POST /lessons/start` → one 202, one 409;
  - a reply with a duplicate `pattern_type` → one mistake row;
  - a foreign-issuer token → 401 when `APP_ENV=production`;
  - a stale generating lesson → start succeeds;
  - finish returns before the report LLM call, which is checked with a slow `fake_llm`.
  - Part F: messages 1, 3 and 40 minutes apart → `active_minutes` counts the 40-minute gap as the idle cap;
  - Part F: `suggest_finish=true` from `fake_llm` at 5 of 15 min → stored as false;
  - Part F: a `solid` practiced result on a due mistake → `next_review_at` moves out.
  - Part F: finish at 8 of 15 min → `accomplished`, `finished_early=true`, `shortfall_minutes=7`.
  - Part F: accept without `minutes_per_session` → 422 `TIME_BUDGET_REQUIRED`; start for such a profile → 409 `TIME_BUDGET_REQUIRED`.
  - D5: `GET /lessons/not-a-uuid` → 422; a well-formed id owned by someone else → 404.
  - D13: the app boots with only `GEMINI_*` set (alias, warning logged) and with only `LLM_*` set.
- Part F eval (PR 7 dataset `lesson_turns`): a fast learner at 6 of 15 min with all targets met → the reply continues practicing and doesn't recap. A "skip" message → the reply offers a variant of the same item.
- `docker compose up` and a manual flow: sign in → onboarding → accept → start lesson → chat → finish → reports render.
- PR 7: the app refuses to start with `APP_ENV=production` and `LANGSMITH_TRACING=true`. A staging chat turn shows up in the `lingua-coach-staging` project.
- PR 7: `uv run python -m evals.run --dataset lesson_turns` creates an experiment visible in the LangSmith UI. Compare two prompt versions there.
- Frontend: `npm run lint && npm run typecheck`, then a manual chat smoke test.
