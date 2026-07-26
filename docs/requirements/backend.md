# Backend requirements

Status: **locked** (interview)

## Purpose

FastAPI service that authenticates learners, owns learner state, orchestrates lessons and chat, and exposes REST + SSE APIs to the frontend. LLM calls go through the AI API layer; durable state lives in Postgres.

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
- Profile CRUD
- Lesson generation orchestration (async job)
- Progress / mistake logging
- Chat sessions with streamed replies

### Out of scope (MVP)

- Billing / subscriptions
- Free vs premium labels or SKUs
- Admin panel / product analytics
- WebSockets
- Durable job queue (Redis, Celery, ARQ)

## Usage limits (single product version)

- One unlabeled product version (no free/premium split)
- Hard limit: **1 lesson per day** per user
- Enforce on `POST /lessons/today` (calendar day in a defined timezone, default UTC unless product later specifies otherwise)
- Chat remains available within baseline rate limits (see NFRs); lesson cap is the primary product limit

## API transport

| Concern | Mechanism |
|---------|-----------|
| CRUD, jobs, lesson fetch | REST (JSON) |
| Chat token streaming | SSE (`text/event-stream`) |
| Real-time bidirectional | Not in MVP (no WebSocket) |

Transport choice does not constrain LLM provider choice; providers are called from the server side only.

## Async model

### Chat

- One HTTP request per turn
- Response streams via SSE
- Persist final message + side effects after stream completes (or on `done` event)

### Lesson generation

1. `POST /lessons/today` → `202` + `{ "job_id": "..." }` (or `429`/`403` if daily lesson already consumed)
2. In-process worker runs learning-engine steps
3. Client polls `GET /jobs/{job_id}` until `done` | `failed`
4. Client loads `GET /lessons/{id}` for structured lesson JSON

**MVP trade-off:** in-process jobs can be lost on process restart; acceptable until a real queue is introduced.

## Illustrative endpoints

```
# Auth / identity
POST   /auth/sync                 # ensure Postgres user exists for Clerk subject

# Profile
GET    /profile
PATCH  /profile

# Lessons + jobs
POST   /lessons/today             # start generation → job_id (1/day)
GET    /jobs/{job_id}
GET    /lessons/{lesson_id}

# Progress
GET    /progress
POST   /progress/events

# Chat
POST   /chat/sessions
GET    /chat/sessions/{session_id}
POST   /chat/sessions/{session_id}/messages   # Accept: text/event-stream
```

Exact paths may be versioned (`/api/v1/...`) at implementation time.

## SSE chat contract (MVP)

- Client sends message body as JSON on POST
- Server emits events, e.g. `token` (partial text) and `done` (message id, optional corrections metadata)
- Errors mid-stream: emit an `error` event then close

## Non-functional requirements (MVP baseline)

| NFR | Requirement |
|-----|-------------|
| Environments | `local` and `prod` config via env vars |
| CORS | Allow configured frontend origin(s) only |
| Auth | Reject missing/invalid Clerk JWT with `401` |
| Rate limiting | Per-user limits on chat and lesson-start endpoints (protect free LLM quotas) |
| LLM timeouts | Configurable request timeouts; fail job/chat cleanly |
| Logging | Structured logs with request id, user id, job id where applicable |
| Secrets | Clerk keys, DB URL, LLM keys via env / secret store — never in repo |

## Dependencies on other docs

- [ai-api.md](./ai-api.md) — provider abstraction, streaming, structured lesson JSON
- [database.md](./database.md) — schema for users, lessons, jobs, progress, chat
- [frontend.md](./frontend.md) — Clerk SDK, REST client, SSE consumer, job polling
- [deployment.md](./deployment.md) / [hosting.md](./hosting.md) — how the API process is run

## Open for later (not MVP)

- Redis/ARQ (or similar) for durable lesson jobs
- WebSocket for push (“lesson ready”) or interrupt-generation
- Billing and multi-tier limits
- Soft caps beyond 1 lesson/day (e.g. chat minute budgets) if free-API cost requires it
