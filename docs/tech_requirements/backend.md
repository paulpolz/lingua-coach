# Backend requirements

Status: **locked** (interview)

## Purpose

FastAPI service that authenticates learners, owns learner state, orchestrates onboarding and sequential lessons, and exposes REST + SSE APIs to the frontend. LLM calls go through the AI API layer; durable state lives in Postgres.

The **learning engine** loads agent skills from [skills/](../../skills/README.md) and maps them to chat modes and lesson jobs. All skill artifacts are persisted per [database.md](./database.md).

## Stack

| Item | Choice |
|------|--------|
| Framework | FastAPI (Python) |
| Auth | Clerk — magic link / email only, **no Google OAuth** |
| Session model | Verify Clerk JWT per request (JWKS). Do **not** store JWTs as session source of truth in Postgres |
| App identity | Upsert `users` row keyed by `clerk_user_id` after first authenticated request |
| Database | PostgreSQL (see [database.md](./database.md)) |
| Job runner (MVP) | In-process (`BackgroundTasks` / asyncio). No Redis/Celery |

## MVP scope

### In scope

- Auth bridge (Clerk → Postgres user)
- **`onboarding_interviewer`** — onboarding chat + profile persistence
- **`course_composer`** — plan in chat + acceptance gate
- **`exercise_tutor`** — sequential lesson generation, coaching, mistakes, session summary
- Profile / learning goals (read; **writes from chat** and onboarding acceptance)
- Sequential lesson generation on demand (async job)
- Lesson stop / finish lifecycle
- Progress / mistake logging (MVP-light; no `feedback_giver` pipeline)
- Chat sessions with streamed **text** replies (onboarding + lesson modes); messages are plain text only — no audio/video upload or STT/TTS in MVP
- In-chat plan adaptation (`plan_updates` from chat)
- **Plan schedule & pacing** — target plan days, 24h on-pace rule, reschedule on slip

### Out of scope (MVP)

- **`feedback_giver`** — progress dashboard, weekly assessment gates, automated replans, structured progress updates ([feedback_giver.md](../../skills/feedback_giver.md))
- Billing / subscriptions
- Free vs premium labels or SKUs
- Admin panel / product analytics
- Analysis / skill analytics APIs
- Dedicated plan-editor PATCH endpoints for UI forms (plan changes via chat only)
- WebSockets
- Durable job queue (Redis, Celery, ARQ)
- **Calendar-assigned lessons** (no “today’s lesson on March 15”); sequential on-demand only
- **Blocking** the user from starting the next lesson when behind pace (slip updates projection only)

## Lesson rules (sequential, on demand)

- Lessons are numbered **`lesson_number`** 1, 2, 3, … per user (integer, monotonic).
- Lessons are **not pre-generated**. `POST /lessons/start` creates the **next** lesson when the user is ready.
- **At most one active lesson** per user (`status = active` or `generating`). Return `409 Conflict` if user tries to start while one is active.
- Generation input includes: active learning plan, profile, **prior lessons**, `progress_events`, and `mistakes`.
- After **`accomplished`**, user may start the next lesson.

## Plan schedule and pacing

**Concept:** At onboarding accept, the plan includes **`target_plan_days`** (estimated accomplished lessons to reach the goal). Each accomplished lesson = one plan day. **Not** tied to calendar dates.

| Rule | Behavior |
|------|----------|
| **On pace** | User finishes within **24 hours** of lesson `started_at` (`started_at` set when status → `active`) |
| **Slip / reschedule** | If finish is **after 24h** from `started_at`: increment `plan_slip_days` by **1**, recompute `projected_completion_at`, emit `plan_rescheduled` progress event |
| **Stop / resume** | Pausing does **not** reset the window; elapsed time continues until finish or abandon (not MVP) |
| **No blocking** | User may always start the next lesson after accomplish; slip only affects projection |
| **Plan changes** | Chat `plan_updates` may change `target_plan_days` → recompute projection |

**When projection runs:** on `POST /onboarding/accept`, on `POST /lessons/{id}/finish` (after pace check), and when validated `plan_updates` change schedule fields.

**Initial projection (accept):** `projected_completion_at` ≈ accept time + `target_plan_days` × 24h at ideal one-lesson-per-window pace (display may round to calendar days).

## Lesson lifecycle

| Transition | Trigger | Result |
|------------|---------|--------|
| → `generating` | `POST /lessons/start` | Job runs; `lesson_number = max + 1` |
| → `active` | Job success | Lesson JSON persisted; **`started_at` set**; chat session available |
| Stay `active` | User stops session / leaves chat | No status change; resumable; pace clock keeps running |
| → `accomplished` | `POST /lessons/{id}/finish` | Progress finalized; **pace evaluated**; schedule may reschedule; next start allowed |
| Job failure | Worker error | `failed` row or job failed; user can retry start |

**Stop vs finish (MVP):**

- **Stop:** end chat session; lesson remains **`active`**. User resumes via existing lesson + chat session.
- **Finish:** explicit user action; mark **`accomplished`**, emit `lesson_completed` progress event, persist aggregated session mistakes. Required before starting the next lesson.

Tutor may include a `suggest_finish` hint in chat `done` metadata; finishing still requires the explicit finish action in MVP.

## Onboarding gate

- New users have `onboarding_complete = false` until plan acceptance.
- Onboarding uses chat sessions with `type = onboarding`.
- `POST /onboarding/accept` (or equivalent) persists accepted plan (including **`target_plan_days`**) + sets `onboarding_complete = true` + initial `projected_completion_at`.
- Main lesson routes require `onboarding_complete`.

## Plan adaptation (chat-only)

- During onboarding or lesson chat, the AI layer may return **`plan_updates`** in the stream `done` payload.
- Backend validates and applies updates to `profiles` / `learning_goals` — no separate plan-editor API for MVP.
- Log plan changes for audit/debug.

## API transport

| Concern | Mechanism |
|---------|-----------|
| CRUD, jobs, lesson fetch | REST (JSON) |
| Chat token streaming | SSE (`text/event-stream`) |
| Real-time bidirectional | Not in MVP (no WebSocket) |

## Async model

### Chat

- One HTTP request per turn
- Response streams via SSE
- Persist final message + plan side effects after stream completes (on `done`)

### Lesson generation

1. `POST /lessons/start` → `202` + `{ "job_id": "..." }` (or `409` if active lesson exists)
2. In-process worker runs learning-engine step using prior lesson history
3. Client polls `GET /jobs/{job_id}` until `done` | `failed`
4. Client loads `GET /lessons/{id}` for structured lesson JSON

**MVP trade-off:** in-process jobs can be lost on process restart; acceptable until a real queue is introduced.

## Illustrative endpoints

```
# Auth / identity
POST   /auth/sync                      # ensure Postgres user exists for Clerk subject

# Profile (read-heavy; writes via chat/onboarding)
GET    /profile                        # includes schedule: target_plan_days, plan_days_done, projected_completion_at, pace summary

# Onboarding
POST   /onboarding/accept              # persist accepted plan + schedule; set onboarding_complete

# Lessons + jobs
POST   /lessons/start                  # generate next lesson on demand
GET    /lessons/active                 # current generating/active lesson, if any
GET    /jobs/{job_id}
GET    /lessons/{lesson_id}
POST   /lessons/{lesson_id}/finish     # mark accomplished; evaluate 24h pace; maybe reschedule
POST   /lessons/{lesson_id}/stop       # optional explicit stop (else UI leaves session)

# Progress
GET    /progress                       # plan days done, on pace / behind, slip, projection
POST   /progress/events

# Chat
POST   /chat/sessions                  # type: onboarding | lesson
GET    /chat/sessions/{session_id}
POST   /chat/sessions/{session_id}/messages   # Accept: text/event-stream
```

Exact paths may be versioned (`/api/v1/...`) at implementation time.

## SSE chat contract (MVP)

- Client sends message body as JSON on POST
- Server emits events, e.g. `token` (partial text) and `done` (message id, optional corrections metadata, optional `plan_updates`)
- Errors mid-stream: emit an `error` event then close

## Non-functional requirements (MVP baseline)

| NFR | Requirement |
|-----|-------------|
| Environments | `local` and `prod` config via env vars |
| CORS | Allow configured frontend origin(s) only |
| Auth | Reject missing/invalid Clerk JWT with `401` |
| Rate limiting | Per-user limits on chat and lesson-start endpoints (protect LLM quotas) |
| LLM timeouts | Configurable request timeouts; fail job/chat cleanly |
| Logging | Structured logs with request id, user id, job id where applicable |
| Secrets | Clerk keys, DB URL, LLM keys via env / secret store — never in repo |

## Dependencies on other docs

- [skills/README.md](../../skills/README.md) — agent behavior source of truth
- [ai-api.md](./ai-api.md) — onboarding chat, lesson generation, plan updates, streaming
- [database.md](./database.md) — schema for users, lessons, jobs, progress, chat
- [frontend.md](./frontend.md) — Clerk SDK, REST client, SSE consumer, job polling
- [cjm.md](../functional_requirements/cjm.md) — journey alignment
- [deployment.md](./deployment.md) / [hosting.md](./hosting.md) — how the API process is run

## Open for later (not MVP)

- **`feedback_giver`** skill pipeline after lesson finish
- Redis/ARQ (or similar) for durable lesson jobs
- WebSocket for push (“lesson ready”) or interrupt-generation
- Analysis / skill breakdown APIs
- Billing and multi-tier limits
- Abandon lesson (force-drop active lesson without finish)
