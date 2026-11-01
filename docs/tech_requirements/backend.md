# Backend

FastAPI service in [`apps/backend`](../../../../apps/backend). It authenticates Clerk users, stores learner data in Postgres, runs the coach chat as one JSON response per turn, generates lessons in a background task, and exposes Prometheus metrics.

## Layout

```
apps/backend/
  app/
    main.py            app, middleware, exception handlers, /metrics
    config.py          settings from environment / .env
    api/deps.py        Clerk principal, current user, onboarding gate
    api/v1/            routers: health, auth, chat, onboarding, profile, progress, reports, lessons, jobs
    core/              clerk_auth (JWKS), errors, logging (JSON), metrics, request-id middleware
    db/                engine and AsyncSession factory
    models/            SQLAlchemy tables (see database.md)
    schemas/           HTTP models, plus Gemini response models in llm.py
    services/
      gemini.py            generate_structured over LangChain
      skills.py            loads skills/*.md
      prompt_assembly.py   joins skill markdown and the language policy
      lesson_generation.py background job that writes a curriculum
      report_writer.py     patches the markdown reports after a lesson
      report_seed.py       initial report markdown
      report_ops.py        append_entry / patch_section on section markers
      pace.py              pace status, projection, pace summary
      llm_usage.py         per-user and global Gemini limits
  skills/              coach pedagogy as markdown (loaded at runtime)
  tests/               pytest: unit/, integration/, api/, contract/, eval/
  alembic/             migrations
```

Routers hold the orchestration for their flow. Services hold anything shared between routers or anything that talks to Gemini.

## Endpoints

All routes are under `/api/v1` and, except `health`, require `Authorization: Bearer <Clerk session JWT>`.

| Method | Path | Gate | Purpose |
|--------|------|------|---------|
| GET | `/health` | none | Liveness |
| POST | `/auth/sync` | token | Upsert the `users` row for the Clerk user; returns `onboarding_complete` |
| POST | `/chat/sessions` | synced user | Get or create the onboarding session, or the session for a lesson (`{type, lesson_id?}`) |
| GET | `/chat/sessions/{id}/messages` | owner | Transcript with per-message metadata |
| POST | `/chat/sessions/{id}/messages` | owner | Send a message; `200` `ChatTurnResponse` |
| POST | `/onboarding/accept` | synced user | Accept a roadmap (`{session_id, course_roadmap}`) |
| GET | `/profile` | synced user | Profile summary plus schedule and pace |
| GET | `/progress` | onboarded | Plan days done, target, slip, projection, pace summary, active lesson |
| GET | `/reports/{report_type}` | onboarded | One markdown report (`progress`, `errors_log`, `roadmap`, `four_week_plan`) |
| POST | `/lessons/start` | onboarded | Create lesson N+1 and a generation job; `202 {job_id, lesson_id, lesson_number}` |
| GET | `/lessons/active` | onboarded | The generating or active lesson, or `null` |
| GET | `/lessons/{id}` | onboarded, owner | One lesson with its payload |
| POST | `/lessons/{id}/stop` | onboarded, owner | Leave the chat; logs `lesson_chat_stopped` |
| POST | `/lessons/{id}/finish` | onboarded, owner | Finish an active lesson (`{completed_slot_ids?, learner_feedback?}`) |
| GET | `/jobs/{id}` | owner | Generation job status: `pending`, `running`, `done`, `failed` |
| GET | `/metrics` | none | Prometheus exposition (when `METRICS_ENABLED`) |

"Synced user" means a `users` row exists (`401 USER_NOT_SYNCED` otherwise). "Onboarded" adds `users.onboarding_complete` (`403 ONBOARDING_INCOMPLETE` otherwise). Ownership failures return `404 NOT_FOUND`.

## Authentication

```mermaid
sequenceDiagram
  participant B as Browser
  participant C as Clerk
  participant F as Next.js
  participant A as FastAPI
  B->>C: sign in
  C-->>B: session cookie
  F->>C: getToken()
  F->>A: POST /auth/sync (Bearer JWT)
  A->>C: fetch JWKS (cached)
  A->>A: verify RS256, issuer, exp
  A-->>F: {user_id, onboarding_complete}
```

[`core/clerk_auth.py`](../../../../apps/backend/app/core/clerk_auth.py) verifies the token against the issuer's JWKS. With `CLERK_JWT_ISSUER` set, the issuer must match exactly; without it, any `https://*.clerk.accounts.dev` issuer is accepted.

## Chat turn

One endpoint serves both onboarding and lesson chat. The session type decides the skills and the artifacts.

```mermaid
sequenceDiagram
  participant F as Frontend
  participant A as chat.py
  participant L as llm_usage
  participant G as Gemini
  participant D as Postgres
  F->>A: POST /chat/sessions/{id}/messages {content}
  A->>A: validate length (MAX_MESSAGE_CHARS)
  A->>L: per-user chat limit
  A->>D: last CHAT_CONTEXT_MESSAGES-1 messages
  A->>A: build system instruction + context
  A->>L: reserve global RPM / TPM / RPD
  A->>D: save user message and commit
  A->>G: generate_structured
  A->>D: save artifacts + assistant message
  A-->>F: 200 {message_id, content, metadata}
```

The body is `ChatTurnResponse`: `message_id`, `content`, and `metadata`. History sent to the model is the saved assistant prose. The lesson-context turn is not written back.

Artifacts saved per session type:

- **Onboarding**: a present `learner_profile` upserts `profiles` and the draft `learning_goals` row. `metadata.course_roadmap_draft` is `model_dump()` of a present `course_roadmap` and is not stored until accept. Onboarding metadata has empty `corrections` and `tips`, `suggest_finish: false`, and `plan_updates` of `goal_summary` and `level` only when a profile was saved.
- **Lesson**: `LessonReply` carries corrections, tips, mistakes, plan updates, `suggest_finish`, `lesson_plan`, and `completed_task_ids`. Mistakes are upserted by `pattern_type`. Plan updates patch the profile and write a `plan_updated` event. `task_update` is `{completed_task_ids}` when that list is non-empty, otherwise null.

`metadata` always has the keys `corrections`, `tips`, `plan_updates`, `suggest_finish`, `course_roadmap_draft`, `lesson_plan`, and `task_update`. It is stored on the assistant message so the transcript reloads with the same state. A blank `content` fails schema validation and never reaches persist.

The user row is committed before Gemini. Gemini failures use the `{detail, code}` body and save no assistant row:

| Code | Status |
|------|--------|
| `LLM_TIMEOUT` | 504 |
| `LLM_QUOTA_EXCEEDED` | 429 |
| `LLM_SCHEMA_ERROR`, `LLM_API_ERROR`, `LLM_CONFIG_ERROR` | 502 |
| `PERSIST_FAILED` | 500 |

`PERSIST_FAILED` happens after a valid model, so the usage row stays `ok`. The user row stays; the assistant row does not.

## Onboarding accept

`POST /onboarding/accept` requires the onboarding session and a draft goal. In one transaction it:

1. inserts an `accepted` `learning_plans` row with the roadmap as sent;
2. points `profiles.active_learning_plan_id` at it, sets `target_plan_days` from `roadmap.summary.target_plan_days`, and sets `projected_completion_at = now + target × pace window`;
3. activates the goal and sets `users.onboarding_complete` and `plan_accepted_at`;
4. seeds the Roadmap and 4-Week Plan reports from the roadmap;
5. deletes the onboarding messages and session.

## Lesson lifecycle

```mermaid
stateDiagram-v2
  [*] --> generating: POST /lessons/start
  generating --> active: job done (started_at set)
  generating --> failed: job failed
  active --> active: chat turns, stop, resume
  active --> accomplished: POST /lessons/{id}/finish
  accomplished --> [*]
  failed --> [*]
```

**Start.** Rejected with `409 ACTIVE_LESSON_EXISTS` (and `active_lesson_id`) when a lesson is generating or active. The rule is enforced in the app; a partial index on in-flight lessons keeps the lookup fast. Counts against the per-user lesson-start limit. Creates the lesson with `lesson_number = max + 1` and a `jobs` row, then schedules `run_lesson_generation_job` with FastAPI `BackgroundTasks`.

**Generation job.** Runs after the response, in its own DB session. It marks the job `running`, reads the accepted roadmap, profile, last five accomplished lessons, and all mistakes, and makes one structured Gemini call. Success stores `payload = {version: 1, curriculum, session_summary: null}` from `LessonCurriculum.model_dump()` (including `partner_session: null`), sets the lesson `active` with `started_at = now`, and marks the job `done` with `result_ref = lesson_id`. A curriculum without slots fails validation and fails the job. Any exception marks both the job and the lesson `failed` with the error text.

**Stop.** Writes a `lesson_chat_stopped` event. The lesson, session, and transcript stay.

**Finish.** Only from `active`.

```mermaid
flowchart TD
  f[POST finish] --> pace{finished - started > pace window?}
  pace -- no --> on[pace_status on_pace]
  pace -- yes --> slip[pace_status slipped, plan_slip_days + 1, recompute projection, plan_rescheduled event]
  on --> sum[session_summary]
  slip --> sum
  sum --> ev[lesson_completed event]
  ev --> rep[report_writer: one structured Gemini call, never raises]
  rep --> del[delete lesson chat messages + session]
  del --> commit[commit]
```

Completed slots come from `completed_slot_ids` when the client sends them; otherwise all slots count as done if any assistant turn set `suggest_finish`; otherwise none. The response is `{accomplished_at, pace_status, schedule_updated}`.

## Pace

[`services/pace.py`](../../../../apps/backend/app/services/pace.py) is shared by finish, `/progress`, and `/profile`.

- Lesson status: `slipped` when elapsed hours exceed `profiles.pace_window_hours` (default 24), else `on_pace`.
- Projection: `now + remaining plan days × pace window`.
- Summary: `not_started` before any lesson; `behind` if the active lesson is past its window or the last finished lesson slipped; `ahead` if the last lesson took at most half the window and `plan_slip_days == 0`; otherwise `on_pace`.

## Limits

[`services/llm_usage.py`](../../../../apps/backend/app/services/llm_usage.py) counts rows in `llm_usage_events`, so limits hold across restarts and processes. Rows are written on a separate session so they commit even if the caller's transaction is still open.

| Limit | Default | Window | Error |
|-------|---------|--------|-------|
| Chat messages per user | 60 | rolling hour | `429 RATE_LIMIT_EXCEEDED` |
| Lesson starts per user | 2 | rolling 24h | `429 RATE_LIMIT_EXCEEDED` |
| Gemini requests (all users) | 15 | rolling minute | `429 LLM_RATE_LIMIT_EXCEEDED` |
| Gemini input tokens (all users) | 250,000 | rolling minute | `429 LLM_RATE_LIMIT_EXCEEDED` |
| Gemini requests (all users) | 500 | rolling 24h | `429 LLM_RATE_LIMIT_EXCEEDED` |

Each Gemini call is reserved before it runs (input tokens estimated at 4 characters per token) and completed afterwards as `ok` or `error`. A known input count is stored for both statuses. The estimate remains only when usage never arrived. `max_retries=0`. A schema failure is not retried. All 429s from these limits carry `Retry-After`.

## Errors and logging

- Every error body is `{"detail": "...", "code": "MACHINE_CODE", ...extra}`. Unhandled exceptions become `500 INTERNAL_ERROR`.
- The request-id middleware reads or creates `X-Request-ID`, echoes it on responses, and logs one JSON access line per request (`/metrics` and `/health` are skipped).
- Gemini calls log `llm_call` with call type, model, status, latency, and tokens.

## Metrics

`prometheus-fastapi-instrumentator` provides HTTP request counts and latency. [`core/metrics.py`](../../../../apps/backend/app/core/metrics.py) adds:

| Metric | Labels |
|--------|--------|
| `llm_requests_total` | `call_type`, `model`, `status` |
| `llm_tokens_total` | `call_type`, `model`, `direction` |
| `llm_request_duration_seconds` | `call_type`, `model` |

`call_type` is `chat`, `lesson_json`, or `report`.
