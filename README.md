# Lingua Coach

A pet project: a **personal language-tutor chat** in the browser. You state a real outcome (job interview in Spanish, travel English in six months). The tutor interviews you, writes a course, then runs short daily lessons. It corrects answers, logs repeating mistakes, and keeps a pace — one unit is one finished lesson, not a calendar slot.

The tutor does not “remember the conversation.” After each important moment it files a structured note (goal, plan, today’s curriculum, error patterns). The next lesson is built from those notes. Accepting a plan or finishing a lesson deletes that transcript; what remains is the distilled record: profile, roadmap, lesson summary, mistakes, and reports. There is no custom model training — orchestration over Gemini, with pedagogy in skills and learner state in the database.

---

## Current capability

The local MVP loop is implemented and runnable.

| Layer | What ships |
| --- | --- |
| **Product loop** | Sign-in → onboarding interview → accept roadmap → dashboard → generate lesson → lesson chat → finish → reports. |
| **Auth** | Clerk (email / magic link). Frontend holds a publishable key; API verifies the session JWT and upserts a `users` row. Sessions are not stored in Postgres. |
| **Frontend** | Next.js App Router: `/` (sync + redirect), `/sign-in`, `/onboarding`, `/dashboard`, `/lesson/[id]`, `/reports/[slug]`. Chat-first UI. |
| **Backend** | FastAPI under `/api/v1`. REST + SSE chat. In-process `BackgroundTasks` for lesson generation (single API replica). |
| **LLM** | Gemini API. Streamed chat (`GEMINI_MODEL_CHAT`, flash-class) and validated lesson JSON (`GEMINI_MODEL_LESSON`, pro-class). |
| **Pedagogy** | Runtime-loaded Markdown in [`skills/`](./skills/README.md): `onboarding_interviewer`, `course_composer`, `exercise_tutor`, `vocabulary_practice_formats`, `report_writer`. |
| **Memory** | Structured artifacts in Postgres: profile, draft/active goal, accepted roadmap, lesson payload, mistake SRS, living markdown reports. Chat rows are split on accept/finish. |
| **Languages** | Onboarding starts in English to collect native then target language, then coaches in the target. |
| **Pace** | Sequential integer lessons. At most one `generating` / `active` lesson. 24-hour on-pace window from `started_at`. |
| **Observability** | Prometheus + Grafana + Loki (Compose `--profile monitoring`). Infra dashboards (API, LLM tokens, errors) plus **AI Quality** wired to `quality_events`. |
| **Quality loop** | Offline eval harness with a CI replay gate; online thumbs/CSAT; batch LLM-as-judge; SQL failure miner. |
| **CI** | GitHub Actions: backend pytest (Postgres 16), frontend lint/typecheck/vitest, `evals-replay` (no Gemini key). |

**Not in this version:** voice / STT / TTS, billing, multi-replica job queue (Redis/Celery), plan-editor UI, `feedback_giver`, RAG / vector retrieval, LangChain, custom model fine-tuning.

Production topology is designed (Vercel + Railway + Clerk + Gemini + Cloudflare) but the daily loop is validated locally. Lesson jobs are unsafe across many API replicas by design.

---

## How the system fits together

Engineer view of tables, routes, and UI triggers as they exist in this repo (not a target architecture).

### Runtime

The learner never holds a Gemini key or a database password.

```
Learner (browser)
    → Next.js  (Vercel · :3000)  — screens, chat box, Clerk token
    → Clerk                     — identity; issues JWT
    → FastAPI (Railway · :8000) — rules, persistence, prompt assembly, SSE
         ├→ PostgreSQL          — system of record
         ├→ Gemini              — LLM
         └→ skills/*.md         — pedagogy IP (system instructions)
```

Local: Docker Compose (Postgres 16, API `:8000`, Next `:3000`, `skills/` volume-mounted). Optional monitoring: Grafana `:3001`, Prometheus `:9090`, Loki `:3100`.

Authenticated request: page `getToken()` → `apiFetch` (Bearer + `X-Request-ID`) → CORS → request-id middleware → route → Clerk JWT → `users` row → handler → SQLAlchemy. Exceptions: `GET /health` and `POST /telemetry/client-errors` skip JWT. `POST /auth/sync` verifies JWT but creates the user if missing. Lesson / progress / report routes also require `users.onboarding_complete`.

### Learner journey

```
Sign in → POST /auth/sync → interview (/onboarding)
    → Accept plan → dashboard
        → Start lesson → generate (job + Gemini) → lesson chat
            → Finish → dashboard
                 ↘ reports (seeded at accept, patched at finish)
```

Resume skips Start: dashboard → existing `/lesson/[id]`. After finish you return to the dashboard. Signed-out users land on Clerk. If `onboarding_complete` is false, `/dashboard` bounces to `/onboarding`; if true, `/onboarding` bounces to `/dashboard`.

| Route | What the learner sees | Enter | Act |
| --- | --- | --- | --- |
| `/` | Sync then redirect | `POST /auth/sync` | `/onboarding` or `/dashboard` |
| `/sign-in` | Clerk hosted sign-in | — | Post-auth → `/` |
| `/onboarding` | Interview + plan card + Accept | sync, create session, load messages | SSE chat; `POST /onboarding/accept` |
| `/dashboard` | Pace strip + Start / Resume / Stop / Finish | sync, `GET /progress`, `GET /lessons/active` | start + poll job/lesson; stop; finish |
| `/lesson/[id]` | Tutor chat + checklist + Finish | `GET /lessons/{id}`; session + messages | SSE chat; stop; finish |
| `/reports/[slug]` | Markdown notebooks | — | `GET /reports/{type}` |

### Four drawers of memory

| Drawer | Meaning | Stored as |
| --- | --- | --- |
| Identity | This signed-in person exists, and whether they have a plan | Clerk + `users` |
| Learner facts | Languages, goal, level, time budget, current roadmap | `profiles`, `learning_goals`, `learning_plans` |
| Today’s session | Exercises planned for this lesson, and the live chat | `lessons.payload` + `chat_*` (chat is temporary) |
| What to do next | Mistakes to review, pace, living reports, tutor-quality ratings | `mistakes`, `progress_events`, `user_reports`, `quality_events` |

`quality_events` is the twelfth table (thumbs, CSAT, sampled judges). Chat `session_id` / `message_id` on those rows are opaque — no FK — because finish deletes the transcript and ratings must survive.

**Identity graph:** `users` is the hub. `profiles` is 1:1. A draft `learning_goal` is required before accept can insert `learning_plans`. `profiles.active_learning_plan_id` points at the accepted plan (cycle). `user_reports` are four rows max per user (`progress`, `errors_log`, `roadmap`, `four_week_plan`).

**Practice graph:** `jobs.result_ref` is a soft pointer to `lessons.id` (not an FK). Onboarding `chat_sessions` have no `lesson_id`. Chat rows die with the session; lessons, mistakes, and events stay.

JSONB the next lesson actually reads:

| Location | Written | Consumed by |
| --- | --- | --- |
| `learning_plans.roadmap` | Plan accept | Lesson generation (structure, current block, milestones) |
| `lessons.payload.curriculum` | Generation job success | Lesson chat slots; finish; next generation (last 5) |
| `lessons.payload.session_summary` | Finish | Next generation; `report_writer` |
| `profiles.*` maps | Interview + optional `plan_updates` | Compact profile block on every lesson-chat turn |

### Rules the code enforces

- **One in-flight lesson.** Start is rejected (`409 ACTIVE_LESSON_EXISTS`; UI treats it as Resume). Finish unlocks the next `lesson_number`.
- **24-hour pace window.** On pace = finish within 24 hours of the lesson becoming `active`. Slip reschedules the projection; it does not block practice.
- **Plan day = accomplished lesson.** No “Tuesday’s unit.” You start when ready; sequence is 1, 2, 3…
- **Accept is a button.** The model can draft a `course_roadmap` in chat; nothing is official until `POST /onboarding/accept`.

### Skills and Gemini call types

One provider, one client (`app/services/gemini.py`). Pedagogy is not hard-coded in Python except for wiring: load skills, assemble prompts, parse fenced JSON, persist artifacts.

| Call | Skills | Output | Trigger |
| --- | --- | --- | --- |
| Chat turn (onboarding) | `onboarding_interviewer` + `course_composer` | SSE tokens + optional `json:learner_profile` / `json:course_roadmap` | `POST /chat/sessions/{id}/messages` |
| Chat turn (lesson) | `exercise_tutor` (+ `vocabulary_practice_formats` on week-end review slots) | SSE + `json:lesson_turn` / `lesson_plan` / `task_update` | Same endpoint, `session.type=lesson` |
| Generate curriculum | `exercise_tutor` + `LESSON_GENERATION_CONTRACT` | Validated `LessonCurriculum` JSON | Background job from `POST /lessons/start` |
| Patch reports | `report_writer` + `REPORT_PATCH_CONTRACT` | `json:report_ops` applied to markdown sections | `POST /lessons/{id}/finish` (best-effort) |

Hidden fences and backend effect:

| Fence | Effect |
| --- | --- |
| `json:lesson_turn` | Corrections/tips → message metadata; `mistakes[]` upsert (SRS +1/+3/+7/+14 days); optional `plan_updates` on profile; `suggest_finish` |
| `json:lesson_plan` / `json:task_update` | UI checklist only |
| `json:learner_profile` | Onboarding: upsert `profiles` + draft goal |
| `json:course_roadmap` | Onboarding: draft in `done.metadata` until Accept |

Prompt assembly is shared (`app/services/prompt_assembly.py`). Production loads ORM rows then calls the same helpers the eval runner uses, so assembled strings cannot drift from the API.

### Key flows

**1. Sign-in → sync → gate.** Clerk finishes in the browser. Pages attach `Authorization: Bearer <session JWT>` and `X-Request-ID`. Sync creates the Postgres user if needed and returns `onboarding_complete` for the redirect.

**2. Onboarding → accept.** One chat session for interviewer and course composer. Structured facts ride as hidden fenced JSON; the learner sees prose (and a plan card when a valid `course_roadmap_draft` appears). Accept inserts the plan, points the profile at it, sets the 24h schedule, activates the goal, seeds roadmap + 4-week reports, deletes the interview chat, and sets `onboarding_complete`.

**3. Start → generate.** `POST /lessons/start` returns 202 with real IDs (`generating` + `pending` job), then `BackgroundTasks` continues. Prompt = profile + accepted roadmap + last 5 accomplished payloads + open mistakes. Success writes `payload.curriculum`, sets `started_at` (pace clock), marks the job done. Failure marks both failed — not treated as a learner failure. Dashboard polls `GET /jobs/{id}` (fresh start) or `GET /lessons/{id}` (reload-while-generating).

**4. Lesson chat (SSE).** Persist user message → assemble prompt (curriculum snippet + compact profile including due mistakes as a leading user turn, then last 10 real messages) → stream Gemini → parse fences → write artifacts → SSE `done` with metadata. Events: `token`, `done`, `error`. Gemini errors become SSE `error`, not HTTP 500. Onboarding uses the same SSE shape without the curriculum/mistakes block.

**5. Finish.** Write `session_summary` (client `completed_slot_ids`, else all slots if any `suggest_finish`, else empty). Set `pace_status`. If slipped: `plan_slip_days += 1`, recompute projection. Best-effort `report_writer` patch on progress + errors_log. Delete this lesson’s chat. Finish is never blocked by missing CSAT.

### Layers in the repo

```
apps/
  frontend/          # Next.js — pages, ClerkProvider, lib/* REST+SSE clients
  backend/           # FastAPI — /api/v1, deps, ORM, services, Alembic
skills/              # Markdown loaded at runtime as system_instruction
evals/               # Offline suites, judges, miner, replay fixtures
docs/mvp/            # Locked contracts + dated improvement notes
infra/monitoring/    # Prometheus / Grafana / Loki provisioning
docker-compose.yml
```

| Layer | Path | Job |
| --- | --- | --- |
| UI | `apps/frontend` | App Router, chat, dashboard, reports, quality clients |
| HTTP API | `apps/backend/app/api/v1` | FastAPI routers |
| Auth deps | `apps/backend/app/api/deps.py` | JWT → Clerk principal → `User` → onboarding gate |
| ORM | `apps/backend/app/models` | SQLAlchemy 2; Alembic migrations |
| Services | `apps/backend/app/services` | Gemini, skills, extraction, prompt assembly, jobs, pace, reports, quality |
| Pedagogy | `skills/` | System instructions |
| Evals | `evals/` | Replay gate, live judges, miner |
| Contracts | `docs/mvp/init/tech_requirements/` | Locked API / DB / UI / AI / hosting docs |

Run locally: [`apps/README.md`](./apps/README.md). Locked contracts: [`docs/mvp/init/tech_requirements/README.md`](./docs/mvp/init/tech_requirements/README.md). Skills: [`skills/README.md`](./skills/README.md).

---

## Quality evals

Merged in [`480a4a16`](https://github.com/paulpolz/lingua-coach/commit/480a4a16a47853ff2aa7f2ad58fea8dbfaa6de25). Infra already answered “did the request succeed?” and “how slow / expensive?”. This loop answers whether the tutor was *good*: stayed in the learning language, corrected a real error, did not invent curriculum. The product goal is decisions: **ship / don't ship / rollback / rewrite a skill** — not another dashboard.

```
PostgreSQL     = what happened for this learner
Prometheus     = did the system work (latency, tokens, 5xx, retries)
Eval loop      = was the AI good — and should we change it?

SQL context  = what we know about the learner
Skills       = what the agent is supposed to do
Offline      = do we still do that on known cases?
Online       = is production drifting?
Mining       = which new cases enter the suite this week?
```

Evals must exercise the same prompt the API sends. `app/services/prompt_assembly.py` is the single concatenator (skills + extraction contracts + language policy + compact context). The runner loads YAML fixtures and calls those helpers; production loads ORM rows and calls the same functions. Pedagogy stays in `skills/*.md`.

### Four suites

| Suite | Question | Ship gate? |
| --- | --- | --- |
| **Capability** (`evals/cases/capability/`) | Can the agent still do the job? Gold onboarding / lesson-chat / lesson-generation cases. | Deterministic checks must pass (local / nightly). Not the CI job. |
| **Regression** (`evals/cases/regression/`) | Does this exact failure come back? Gold + known-bad pairs. | **Yes.** CI + `baseline.json`. Zero **new** gated failures. |
| **Calibration** (`evals/cases/calibration/`) | Is the judge itself trustworthy? Author-proposed `labels:` vs judge scores. | No. Agreement / self-consistency only. |
| **Inbox** (`evals/cases/inbox/`) | Miner stubs from production-shaped SQL. | No until a human promotes after stripping PII. Gitignored YAML. |

`--suite all` = capability + regression. Calibration and inbox are never a ship gate; a check failure there does not exit 1 (harness errors still do). Modes: `onboarding` | `lesson` | `lesson_generation`. A case YAML names an id, suite, mode, locale (`native` / `target`), a fixture, a user message (omitted for generation), and `checks`. `system_from_skills: true` is always assembled via production helpers.

### Replay vs live

```bash
# Ship gate — CI and local. Never calls Gemini (tutor or judge).
PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay

# Live Gemini (needs GEMINI_API_KEY). Judges run after deterministic pass
# when checks.judge is set. --no-judge skips them.
PYTHONPATH=apps/backend:. python -m evals.run --suite capability   # also: regression, all

# Calibration (not a gate)
PYTHONPATH=apps/backend:. python -m evals.run --suite calibration --replay --agreement
PYTHONPATH=apps/backend:. python -m evals.run --suite calibration --agreement --self-consistency 3
```

**Replay** loads `evals/fixtures/replay/<id>.json` (`raw_completion`, or `completions[]` for schema-repair — checks run on the last string). CI has no `GEMINI_API_KEY`. Optional canned scores: `evals/fixtures/replay/<id>.judge.json`. **Live** calls the real tutor path, then (if configured) one Gemini `generate_json` judge with a fixed rubric markdown — repair-once, same pattern as lesson generation.

Each run is tagged with `model`, `skill_sha` (git tree of `skills/` at HEAD), `git_sha`, and `rubric_version` (`v1`). Results: `evals/results/<run_id>.json` (gitignored) plus a markdown summary on stdout.

`expect_fail: true` is for known-bad replay completions: the case **passes** only if a listed check fails. If those checks unexpectedly pass, the case fails. That keeps the detector honest. After an intentional skill / prompt / contract change: run live, confirm behavior (not only JSON parse), copy new completions into replay files, refresh `evals/fixtures/baseline.json` `failed_ids` if the known-fail set changed, land replay + baseline **in the same PR** as the skill change.

### Deterministic checks (the gate)

These run first. Do not spend tokens judging invalid output. Unknown check names are always a case error (not inverted by `expect_fail`). Judge scores **never** change the process exit code.

| Check | Pass when |
| --- | --- |
| `extract_lesson_turn` | Last valid `json:lesson_turn` parses |
| `extract_learner_profile` | Last valid `json:learner_profile` parses |
| `extract_course_roadmap` | Last valid `json:course_roadmap` parses |
| `no_english_learner_facing` | Stripped learner-facing prose has no English explanation markers (`locale.target` ≠ `en`; JSON **keys** ignored) |
| `roadmap_target_language_matches` | Roadmap `summary.target_language` matches `locale.target` |
| `pattern_type_articles` | A mistake/correction label contains `article` |
| `curriculum_valid` | Completion JSON validates as `LessonCurriculum` |
| `grammar_focus_aligned` | `grammar_focus` overlaps fixture roadmap theme / milestone |
| `exit_criteria_nonempty_unique` | Exit criteria non-empty, non-blank, unique |
| `invented_milestone` | `milestone_index` exists on the fixture roadmap |
| `one_question_rule` | At most one `?` in stripped prose |

### Judges (informational)

| Rubric | Dimensions |
| --- | --- |
| `lesson_turn_v1` | Immersion, correction accuracy, pedagogy, contract |
| `lesson_generation_v1` | Groundedness, difficulty, immersion (schema is deterministic only) |
| `onboarding_v1` | Completeness, one-question rule, roadmap honesty |

A rubric edit is a new file (`lesson_turn_v2`); never silently compare v1 to v2. `--self-consistency 3` re-judges the same completion three times (live) and flags dimension flips. `--agreement` compares scores (or canned `.judge.json`) to calibration `labels:` and prints % agree and Cohen’s κ per dimension. First labels are **author-proposed**. Independent double-label + agreement ≥ ~0.7 is required before any judge dimension becomes a ship gate. Drop a noisy dimension rather than theatrical scores.

### CI

`.github/workflows/ci.yml` runs three jobs on every PR and every push to `main`: `backend-test` (Postgres 16 + `uv run pytest`), `evals-replay` (`python -m evals.run --suite regression --replay` — **no API key**), `frontend-test` (lint, typecheck, vitest). `evals-replay` can be a required status check after the first green run on `main`. Pytest with a mocked Gemini still guards contracts; a skill change can also fail CI because a regression case failed replay. That is the ship gate.

### Online signals

Do **not** call Gemini on the chat SSE path. Authenticated `POST /api/v1/quality/events` stores:

- **Thumbs** on assistant bubbles after SSE `done` (`kind=thumbs`, `value.thumb` = `1` or `-1`). Surfaces: onboarding and lesson. Fire-and-forget `204`.
- **Lesson CSAT** optional 1–5 on Finish (`kind=lesson_csat`). Empty is allowed; finish is never blocked. Free-text `learner_feedback` still lands on `session_summary`.

Chat rows are deleted on finish. Thumbs copy a compact snapshot into the event while the message still exists so a later batch judge has something to score.

```bash
PYTHONPATH=apps/backend:. python -m evals.judge_online [--limit 25]
```

Reads unjudged `judge_candidate` rows (10% of lesson turns with corrections, plus all thumbs-down that still had a snapshot) and writes `kind=judge` (rubric version, scores, model id). If `GEMINI_API_KEY` is unset, the script prints a skip and exits 0.

Grafana dashboard **AI Quality** (`infra/monitoring/grafana/provisioning/dashboards/json/ai-quality.json`): thumbs-down rate by surface, lesson CSAT, judge fail rate by dimension, plus existing infra (HTTP p95, `llm_retries_total`). Empty until events exist. Use it to decide what to mine — not to page, and not to override the replay gate. `llm_retries_total` is format fragility, not quality. Do not rewrite a skill because thumbs dropped on N < 30. Do not switch models because one judge run moved 3 points.

### Failure mining (closed loop)

SQL + rules, no LLM. Writes candidate stubs under `evals/cases/inbox/` (`suite: inbox`). Sources (last N days): thumbs-down and CSAT ≤ 2, finish `learner_feedback`, failed `jobs`, high-occurrence `mistakes` with the same correction. Crude tags: `immersion`, `schema`, `user_too_hard`, `job_fail`, `thumbs_down`.

```bash
PYTHONPATH=apps/backend:. python -m evals.mine [--days 7 --limit 20 --out evals/cases/inbox]
```

**Ritual:** run the miner once a week. Promote 3–5 stubs (or write “nothing to add”): copy to `cases/regression/`, strip PII, set checks, add a replay fixture, confirm `--suite regression --replay`.

Worked example already in-repo (not fabricated prod traffic): Spanish-immersion lesson, English learner turn, tutor must not lecture in English (L1 leakage). `evals/cases/regression/lesson_chat_l1_leakage_es_001.yaml` is gold (`expect_fail: false`). `…_caught.yaml` is a known-bad English lecture (`expect_fail: true` — passes only if `no_english_learner_facing` fails). A skill edit that leaks English on the gold case fails `evals-replay`.

Commands, YAML contract, check catalog: [`evals/README.md`](./evals/README.md). Decisions and noise rules: [`evals/docs/shareable.md`](./evals/docs/shareable.md), [`evals/docs/methodology.md`](./evals/docs/methodology.md). Design note: [`docs/mvp/evals_improvement_20260830/evals_improvement_20260830.md`](./docs/mvp/evals_improvement_20260830/evals_improvement_20260830.md).

---

## Next steps

Immediate product/engine gaps (still post-MVP, not started):

- `feedback_giver` — progress dashboard, weekly gates, automated replans. Session summaries and reports already exist; the closed analysis loop does not.
- **Voice** — STT/TTS; text-only until then.
- **Job queue** — Redis/Celery (or equivalent) before a second API replica. In-process `BackgroundTasks` is a single-instance constraint.
- **Judge calibration** — independent double-label on the calibration set; promote a dimension to the ship gate only after agreement is documented.

The next architecture bet under consideration is **RAG over teaching knowledge**, with **LangChain / LangGraph** for orchestration and **LangSmith or DeepEval** for traces/eval — see [`docs/mvp/llm_improvement_20260823/rag_langchain.md`](./docs/mvp/llm_improvement_20260823/rag_langchain.md). That is a design note, not an implementation.

### What we would change (if we go this way)

Today every Gemini call gets the **same** skill Markdown plus a **SQL-assembled** compact context (profile, roadmap slice, last 5 lessons, due mistakes). That already works; the pain is scale: static instructions do not vary by the learner’s current weakness, and stuffing more history into the prompt is the wrong long-term memory model.

```
PostgreSQL  = what we know about this learner (profile, mastery, errors)
pgvector    = which teaching knowledge is relevant (grammar, templates, error patterns)
LangChain   = how we connect models, prompts, retrieval, tools
LangGraph   = how we control a branching multi-step tutor workflow (only if we need it)
```

Learner facts stay SQL. Teaching material (curriculum snippets, grammar notes, exercise templates, L1 error patterns) would be chunked, embedded, and retrieved with metadata filters (language, CEFR, skill, topic). Hybrid: SQL decides “today’s objective = past tense / travel / A2”; vectors fetch the few relevant chunks; the LLM generates from that, not from the whole skill pack. **Do not embed the user profile.**

| Option | Pros | Cons |
| --- | --- | --- |
| **RAG + pgvector** | Pull only the grammar, templates, and error notes needed for this turn. Postgres stays source of truth. Prompts stay smaller as history grows. | Chunking and embeddings add ops work. Bad retrieval can surface the wrong note or a fake citation. Helps when the knowledge base is large — less so when the skill file is only ~4 KB. Still need retrieval evals. |
| **LangChain** | One toolkit for prompts, retrieval, structured output, streaming, and tools. Fits “student + memory + chunks → lesson.” | We already have Gemini, SSE, Pydantic, and `prompt_assembly`. Adds another layer on a thin SDK, with API churn and little gain if we rewrite working code. |
| **LangGraph** | Clear state machine for “review vs teach vs practice,” retries, human-in-the-loop, and later multi-step agents. | Too much for our two call types today. Onboarding → lesson → chat → finish already lives in FastAPI and the DB. Add it only when a flow truly branches in-process. |

The eval loop in `evals/` is custom and already the ship gate. A library is optional — adopt only if it reduces rubric drift or tracing cost. The evals design note said a 100-line judge module is enough ([§6.2](./docs/mvp/evals_improvement_20260830/evals_improvement_20260830.md)).

| Option | Pros | Cons |
| --- | --- | --- |
| **Keep `evals/`** | Runs in CI with no API key. Custom checks fit this product (no English leakage, invented milestones). Same prompts as production. Miner → inbox → regression is already built. | We maintain rubrics, agreement math, and the runner. No hosted trace UI. The live judge is a Gemini call we own. |
| **LangSmith** | Traces every LLM call, prompt versions, datasets, and comparison runs. Pairs well with LangChain. Hosted evals and annotation queues. | SaaS cost. Learner chat in traces is PII. Overlaps the replay gate we already use to block PRs. Another dashboard beside Grafana. Vendor lock-in on the quality loop. |
| **DeepEval** | Local-first, pytest-style LLM judges. RAG metrics (faithfulness, relevancy) if we add retrieval. | Another framework around judges we already run. Moving v1 rubrics risks silent score drift. Custom immersion and milestone checks stay ours. Does not replace CI replay fixtures. |

Practical order if we proceed: (1) keep the replay gate as the ship decision, (2) split skill Markdown into instructions vs teachable knowledge and add `pgvector` retrieval behind the existing call types, (3) add retrieval-quality cases to `evals/` (deterministic first), (4) consider DeepEval **only** for RAG metrics or LangSmith **only** if we want traces — not as a replacement for `--replay`.

---

## Docs

| Doc | Role |
| --- | --- |
| [skills/README.md](./skills/README.md) | Pedagogy IP — skill files and pipeline |
| [apps/README.md](./apps/README.md) | Local Docker / host run, monitoring profile |
| [evals/README.md](./evals/README.md) | How to run, add a case, update replay |
| [evals/docs/shareable.md](./evals/docs/shareable.md) | Ship-gate decisions, L1-leakage loop, Grafana |
| [docs/mvp/init/tech_requirements/](./docs/mvp/init/tech_requirements/README.md) | Locked backend / AI / DB / frontend / deploy / hosting |
| [docs/mvp/init/implementation-readiness.md](./docs/mvp/init/implementation-readiness.md) | Local MVP gate, env, smoke tests |
| [docs/mvp/init/functional_requirements/cjm.md](./docs/mvp/init/functional_requirements/cjm.md) | Customer journeys |
| [docs/mvp/evals_improvement_20260830/evals_improvement_20260830.md](./docs/mvp/evals_improvement_20260830/evals_improvement_20260830.md) | Eval-loop design |
| [docs/mvp/llm_improvement_20260823/rag_langchain.md](./docs/mvp/llm_improvement_20260823/rag_langchain.md) | RAG / LangChain proposal |
| [docs/mvp/monitoring_20260811/monitoring_20260811.md](./docs/mvp/monitoring_20260811/monitoring_20260811.md) | Infra monitoring |
