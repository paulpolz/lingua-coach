# Implementation readiness — local MVP

Status: **active gate for local development and testing**

Single checklist and contract reference for building and validating the MVP **on your machine**. Consolidates [cjm.md](./functional_requirements/cjm.md) and [tech_requirements/](./tech_requirements/README.md).

**Canonical specs:** `docs/tech_requirements/` (linked from the root README).

Production deploy (Vercel, Railway, Cloudflare, prod Clerk) is **out of scope here** — see [Deferred: production](#deferred-production) and [hosting.md](./tech_requirements/hosting.md) when you ship externally.

---

## 1. Scope

### In scope (local MVP)

Everything needed to run and manually test both journeys on `localhost`:


| Area         | Local choice                                                                           |
| ------------ | -------------------------------------------------------------------------------------- |
| Frontend     | Next.js dev server (`http://localhost:3000`)                                           |
| Backend      | FastAPI + Uvicorn with hot reload (`http://localhost:8000`)                            |
| Database     | PostgreSQL via **Docker Compose**                                                      |
| Auth         | **Clerk Development** app (email / magic link; no Google)                              |
| LLM          | **Gemini** API key (Google AI Studio)                                                  |
| Journeys     | New user onboarding + student lesson loop ([cjm.md](./functional_requirements/cjm.md)) |
| Lesson model | Sequential on-demand; one in-flight lesson (`generating` | `active`)                   |
| Plan pacing  | `target_plan_days`; 24h on-pace window; slip reschedules projection (no blocking)      |
| Transport    | REST + SSE chat; in-process lesson jobs                                                |
| Plan edits   | Chat-only (`plan_updates`); no plan editor UI                                          |


### Out of scope (do not build for local MVP gate)


| Category               | Items                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| **Hosting / deploy**   | Vercel, Railway, Cloudflare, custom domain, prod env vars                                        |
| **Prod auth**          | Clerk Production application, prod redirect URLs                                                 |
| **Ops**                | CI/CD, staging, Sentry, APM, Railway backups                                                     |
| **Product (post-MVP)** | Billing, **`feedback_giver`** (progress dashboard, weekly gates), analysis/profile journey, **voice / TTS / in-app audio**, marketing landing page, plan editor UI, abandon-lesson |
| **Infrastructure**     | WebSockets, Redis/Celery, multi API replicas, calendar-assigned lessons                          |
| **Optional polish**    | GitHub branch protection, shared-types package, JSON Schema CI                                   |


---

## 2. Local setup checklist

Complete before feature work beyond scaffold.


| #   | Step                      | Done when                                                                                       |
| --- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| 1   | **Docker** installed      | `docker compose version` works                                                                  |
| 2   | **Clerk Development** app | Email + magic link enabled; Google OAuth off; allowed origin `http://localhost:3000`            |
| 3   | **Gemini API key**        | Key from [Google AI Studio](https://aistudio.google.com/); model IDs chosen                     |
| 4   | **Repo layout**           | `apps/frontend`, `apps/backend`, `skills/`, `docker-compose.yml` (§9) |
| 5   | **Env files**             | `apps/frontend/.env.local` + `apps/backend/.env` from §4 (gitignored); `.env.example` committed |
| 6   | **Postgres up**           | `docker compose up -d` → API connects via `DATABASE_URL` |
| 7   | **Migrations**            | `alembic upgrade head` creates schema (§12) |
| 8   | **Skill pack v0**         | MVP skills in `skills/` (§10) |


### Vendor accounts required locally


| Service                                          | Required? | Notes                                               |
| ------------------------------------------------ | --------- | --------------------------------------------------- |
| [Clerk](https://clerk.com)                       | **Yes**   | Development instance only                           |
| [Google AI Studio](https://aistudio.google.com/) | **Yes**   | Free tier OK                                        |
| GitHub                                           | Optional  | Repo already exists; CI not required for local gate |
| Railway / Vercel / Cloudflare                    | **No**    | Deferred                                            |


---

## 3. Credentials and secrets (local)

**Rule:** Never commit secrets. Never put Gemini or DB credentials in the frontend or Postgres.

```mermaid
flowchart LR
  subgraph browser["Browser localhost:3000"]
    ClerkJWT["Clerk session JWT"]
  end
  subgraph frontendEnv["apps/frontend/.env.local"]
    PubKey["NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"]
    ApiUrl["NEXT_PUBLIC_API_URL"]
    ClerkSecretFE["CLERK_SECRET_KEY"]
  end
  subgraph backendEnv["apps/backend/.env"]
    DbUrl["DATABASE_URL"]
    ClerkSecretBE["CLERK_SECRET_KEY"]
    Gemini["GEMINI_API_KEY"]
  end
  ClerkJWT -->|"Bearer → localhost:8000"| backendEnv
```




| Secret / token        | Where (local)                                    | Never in                |
| --------------------- | ------------------------------------------------ | ----------------------- |
| Clerk publishable key | `apps/frontend/.env.local` (`NEXT_PUBLIC_*`)     | Git                     |
| Clerk secret key      | `apps/frontend/.env.local` + `apps/backend/.env` | Browser bundle, Git     |
| User JWT / session    | Clerk-managed; sent per API request              | Postgres                |
| `GEMINI_API_KEY`      | `apps/backend/.env` only                         | Frontend, Git, DB       |
| `DATABASE_URL`        | `apps/backend/.env` only                         | Frontend, Git           |
| Pedagogy / skills     | Git repo (`skills/`)                             | Verbose production logs |


Clerk JWT verification: JWKS or Clerk SDK with `CLERK_SECRET_KEY`. Do **not** persist JWTs in Postgres.

---

## 4. Environment variables (local)

Commit `**.env.example**` files with placeholder names only. Copy to gitignored `.env.local` / `.env`.

### `apps/frontend/.env.example` → `.env.local`

```bash
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### `apps/backend/.env.example` → `.env`

```bash
APP_ENV=local

DATABASE_URL=postgresql+asyncpg://lingua:lingua@localhost:5432/lingua_coach

CLERK_SECRET_KEY=sk_test_...

GEMINI_API_KEY=...
GEMINI_MODEL_CHAT=gemini-2.0-flash
GEMINI_MODEL_LESSON=gemini-2.0-pro
GEMINI_TIMEOUT_SECONDS=120

CORS_ORIGINS=http://localhost:3000
API_HOST=0.0.0.0
API_PORT=8000

CHAT_RATE_LIMIT_PER_HOUR=60
LESSON_START_RATE_LIMIT_PER_DAY=10
MAX_MESSAGE_CHARS=4000
CHAT_CONTEXT_MESSAGES=10
PACE_WINDOW_HOURS=24
```

### `docker-compose.yml` (Postgres)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: lingua
      POSTGRES_PASSWORD: lingua
      POSTGRES_DB: lingua_coach
    ports:
      - "5432:5432"
    volumes:
      - lingua_pg_data:/var/lib/postgresql/data

volumes:
  lingua_pg_data:
```

---

## 5. Local run workflow

From repo root after setup:

```bash
docker compose up -d
cd apps/backend && alembic upgrade head && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
cd apps/frontend && npm run dev
```

Open `http://localhost:3000` → Clerk sign-in → onboarding → lesson loop.

---

## 6. API contract (MVP v1)

Base path: `/api/v1`. All authenticated routes require `Authorization: Bearer <clerk_jwt>`.

### Common error shape

```json
{
  "detail": "Human-readable message",
  "code": "ACTIVE_LESSON_EXISTS"
}
```


| HTTP  | When                                                     |
| ----- | -------------------------------------------------------- |
| `401` | Missing or invalid JWT                                   |
| `403` | Onboarding not complete (lesson routes)                  |
| `404` | Resource not found or not owned by user                  |
| `409` | Active/generating lesson exists on `POST /lessons/start` |
| `422` | Validation error                                         |
| `429` | Rate limit exceeded                                      |
| `502` | Upstream Gemini failure after retries                    |


### Endpoints

#### `POST /api/v1/auth/sync`

Ensure Postgres user exists. Idempotent.

**Response `200`:**

```json
{
  "user_id": "uuid",
  "onboarding_complete": false,
  "email": "user@example.com"
}
```

#### `GET /api/v1/profile`

**Response `200`:**

```json
{
  "goal_summary": "Get conversational at work in 6 months",
  "level": "B1",
  "time_budget": {
    "minutes_per_session": 20,
    "sessions_per_week": 5,
    "intensity": "moderate"
  },
  "topics": ["meetings", "email", "small talk"],
  "vocab_priorities": ["workplace phrasal verbs"],
  "grammar_mastery": { "articles": 40, "present_perfect": 82 },
  "schedule": {
    "target_plan_days": 90,
    "plan_days_done": 3,
    "plan_slip_days": 1,
    "projected_completion_at": "2026-10-15T12:00:00Z",
    "pace_window_hours": 24,
    "pace_summary": "behind"
  }
}
```

`pace_summary`: `"on_pace"` | `"behind"` | `"ahead"` | `"not_started"`.

#### `POST /api/v1/onboarding/accept`

Explicit product action when the user clicks **Accept plan** in onboarding chat. The client sends the **accepted roadmap JSON** (as composed/refined in chat — see [course_composer.md](../../skills/course_composer.md)) plus the onboarding `session_id`. The backend persists `learning_plans`, sets schedule fields, marks `onboarding_complete`, and **deletes the onboarding chat transcript** (artifacts only).

**Request:**

```json
{
  "session_id": "uuid",
  "course_roadmap": { }
}
```

`course_roadmap` is the full accepted structure (`summary`, `milestones`, `weekly_template`, `current_block`, …) — not inferred from chat history at accept time.

**Response `200`:** `{ "onboarding_complete": true, "plan_accepted_at": "..." }`

#### `POST /api/v1/lessons/start`

**Response `202`:** `{ "job_id": "uuid", "lesson_id": "uuid", "lesson_number": 4 }`

**Response `409`:** `{ "detail": "...", "code": "ACTIVE_LESSON_EXISTS", "active_lesson_id": "uuid" }`

#### `GET /api/v1/jobs/{job_id}`

```json
{
  "id": "uuid",
  "status": "pending",
  "type": "lesson_generate",
  "result_ref": null,
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

`status`: `pending` | `running` | `done` | `failed`

#### `GET /api/v1/lessons/active`

**Response `200`:** lesson object or `null`.

#### `GET /api/v1/lessons/{lesson_id}`

```json
{
  "id": "uuid",
  "lesson_number": 4,
  "status": "active",
  "started_at": "2026-07-27T10:00:00Z",
  "accomplished_at": null,
  "pace_status": null,
  "payload": { }
}
```

#### `POST /api/v1/lessons/{lesson_id}/finish`

User clicks **Finish lesson** (always available while lesson is `active`). Tutor may set `suggest_finish: true` in chat `done` metadata when all planned exercises are done, but finish still requires this explicit action. Early finish is allowed: slots not completed count as **0%** in `session_summary` and reduce aggregated course-progress completion.

**Response `200`:**

```json
{
  "status": "accomplished",
  "accomplished_at": "...",
  "pace_status": "on_pace",
  "schedule_updated": false
}
```

#### `POST /api/v1/lessons/{lesson_id}/stop`

**Response `204`**. Optional; UI may leave chat without calling.

#### `GET /api/v1/progress`

```json
{
  "plan_days_done": 3,
  "target_plan_days": 90,
  "plan_slip_days": 1,
  "projected_completion_at": "...",
  "pace_summary": "behind",
  "active_lesson": {
    "id": "uuid",
    "lesson_number": 4,
    "started_at": "...",
    "hours_remaining_in_pace_window": 18.5
  }
}
```

#### `POST /api/v1/chat/sessions`

**Request:** `{ "type": "onboarding" | "lesson", "lesson_id": "uuid?" }`

**Response `201`:** `{ "id": "uuid", "type": "lesson", "lesson_id": "uuid" }`

#### `POST /api/v1/chat/sessions/{session_id}/messages`

**Request:** `{ "content": "user message text" }`

**Response:** `Content-Type: text/event-stream` — see [§7 SSE](#7-sse-contract).

#### `GET /api/v1/chat/sessions/{session_id}/messages`

**Response `200`:** `{ "messages": [{ "id": "uuid", "role": "user"|"assistant", "content": "...", "created_at": "..." }] }`

Source of truth for chat UI — do not rely on client cache (other devices, cleared storage).

#### `GET /api/v1/health`

**Response `200`:** `{ "status": "ok" }` (no auth).

---

## 7. SSE contract

`POST /chat/sessions/{id}/messages` with `Accept: text/event-stream`.

Format: `event: <name>\ndata: <json>\n\n`

### `token`

```
event: token
data: {"text":"Hello "}
```

### `done`

```
event: done
data: {
  "message_id": "uuid",
  "content": "Full assistant reply text",
  "metadata": {
    "corrections": [],
    "tips": [],
    "plan_updates": null,
    "suggest_finish": false
  }
}
```

`suggest_finish`: tutor signals all planned exercises in the lesson curriculum are done; user still taps **Finish lesson** to accomplish.

### `error`

```
event: error
data: {"code": "LLM_TIMEOUT", "message": "Request timed out"}
```

---

## 8. JSON schemas

Implement as Pydantic (API) + TypeScript types (frontend).

### Time budget

```json
{
  "minutes_per_session": 20,
  "sessions_per_week": 5,
  "intensity": "moderate"
}
```

`intensity`: `"light"` | `"moderate"` | `"intensive"`

### Plan updates (chat `done` metadata)

```json
{
  "goal_summary": "optional string",
  "level": "optional B1|B2|...",
  "time_budget": { },
  "topics": ["optional array"],
  "vocab_priorities": ["optional array"],
  "target_plan_days": 120,
  "grammar_mastery": { "articles": 45 }
}
```

### Lesson JSON (`lessons.payload`)

```json
{
  "lesson_goal": "Practice past tense in workplace retrospectives",
  "grammar_focus": "Past simple vs present perfect",
  "warmup": [{ "type": "prompt", "text": "Describe yesterday's standup in 3 sentences." }],
  "dialogue": [{ "role": "manager", "line": "What blocked you last sprint?" }],
  "exercise": [{
    "type": "fill_blank",
    "prompt": "We ___ (finish) the release on Friday.",
    "answer_hint": "past simple"
  }],
  "review": [{ "type": "recap", "text": "Key pattern: finished + time marker" }]
}
```

Exercise `type` (MVP): `prompt` | `fill_blank` | `rewrite` | `roleplay` | `recap`. Render in chat, not separate panels.

### Chat message metadata (assistant)

```json
{
  "corrections": [
    { "span": "I goed", "correction": "I went", "type": "grammar", "note": "irregular past" }
  ],
  "tips": ["Use 'finished' with a specific time."],
  "plan_updates": null,
  "suggest_finish": false
}
```

---

## 9. Repo layout

```
lingua-coach/
  apps/
    frontend/            # Next.js
    backend/             # FastAPI + alembic/
  skills/                # agent pedagogy IP (source of truth; loaded at runtime)
  docker-compose.yml
  docs/
```

`packages/shared-types/` optional — skip until prod or shared CI.

---

## 10. Pedagogy / skills

**Source of truth:** [skills/](../skills/README.md) at repo root.

Minimum before meaningful local dogfooding:

| Skill file | Purpose |
|------------|---------|
| `onboarding_interviewer.md` | Interview → `profiles` |
| `course_composer.md` | Roadmap → accept → `learning_plans` (same onboarding session) |
| `exercise_tutor.md` | Lesson JSON + coaching + artifacts |
| `vocabulary_practice_formats.md` | Week-end vocab drills (concatenated in lesson chat) |

**Post-MVP:** `feedback_giver.md` — do not wire until analysis journey ships.

| File | Purpose |
|------|---------|
| `config/persona.yaml` | Default ICP (optional) |

Prior-lesson context: last **N=5** accomplished lessons (`lessons.payload` summaries + `mistakes`).

---

## 11. NFR defaults (local)


| Setting                           | Default |
| --------------------------------- | ------- |
| `PACE_WINDOW_HOURS`               | 24      |
| `CHAT_CONTEXT_MESSAGES`           | 10      |
| `MAX_MESSAGE_CHARS`               | 4000    |
| `GEMINI_TIMEOUT_SECONDS`          | 120     |
| `CHAT_RATE_LIMIT_PER_HOUR`        | 60      |
| `LESSON_START_RATE_LIMIT_PER_DAY` | 10      |
| Lesson JSON repair retries        | 1       |


Logging: structured stdout; `request_id`, `user_id`, `job_id`. Avoid logging full prompts locally if they contain PII.

---

## 12. Database (migration v1)

- [ ] `users`, `profiles`, `learning_goals`, `jobs`, `lessons`, `progress_events`, `mistakes`, `chat_sessions`, `chat_messages`
- [ ] Unique `(user_id, lesson_number)`; schedule fields on `profiles`
- [ ] Indexes per [database.md](./tech_requirements/database.md)

---

## 13. Build order (local)


| Phase                | Deliverable                                              | Done when                                       |
| -------------------- | -------------------------------------------------------- | ----------------------------------------------- |
| **0. Scaffold**      | Monorepo, Docker Postgres, `.env.example`, `GET /health` | Health OK on `:8000`                            |
| **1. Auth**          | Clerk in Next.js; JWT in FastAPI; `POST /auth/sync`      | Sign-in → `users` row                           |
| **2. Onboarding**    | Chat SSE + Gemini; `POST /onboarding/accept`             | Plan accepted → dashboard                       |
| **3. Lesson job**    | `POST /lessons/start`, poll job, validate lesson JSON    | Lesson 1 persists                               |
| **4. Lesson chat**   | Lesson session + SSE                                     | Student loop in chat                            |
| **5. Finish + pace** | Finish, slip logic, dashboard hints                      | [Local smoke tests](#14-local-smoke-tests) pass |


**Local MVP complete** when §14 checklist is green. Production deploy is a separate milestone — see [Deferred: production](#deferred-production).

---

## 14. Local smoke tests

Manual checklist — the definition of done for local MVP:

- [ ] `GET http://localhost:8000/api/v1/health` → `{ "status": "ok" }`
- [ ] Clerk dev sign-in on `:3000`
- [ ] `POST /auth/sync` creates user in local Postgres
- [ ] Onboarding chat streams SSE tokens
- [ ] Accept plan → `onboarding_complete`; lesson routes unlocked
- [ ] Start lesson → job completes → valid lesson JSON in DB
- [ ] Second start while active → `409`
- [ ] Lesson chat streams tutor reply
- [ ] Finish lesson → `lesson_completed` event; can start next
- [ ] Finish after 24h (or mocked clock) → `plan_slip_days` increments

---

## 15. Pre-code sign-off (local)

- [ ] Clerk **Development** app; keys in local env
- [ ] Gemini API key; model IDs set
- [ ] `.env.example` committed (no secrets)
- [ ] `docker compose up` → Postgres reachable
- [ ] API paths use `/api/v1/...`
- [ ] Skill pack v0 in `skills/` (phase 0–1)

---

## Deferred: production

When local smoke tests pass and you want external users, use [deployment.md](./tech_requirements/deployment.md) and [hosting.md](./tech_requirements/hosting.md):


| Item                                 | Reference                                                        |
| ------------------------------------ | ---------------------------------------------------------------- |
| Railway (API + Postgres)             | [hosting.md](./tech_requirements/hosting.md)                     |
| Vercel (frontend)                    | [hosting.md](./tech_requirements/hosting.md)                     |
| Cloudflare (domain, SSE proxy notes) | [hosting.md](./tech_requirements/hosting.md)                     |
| Clerk Production app + prod URLs     | [deployment.md](./tech_requirements/deployment.md)               |
| Prod smoke tests                     | [deployment.md §Smoke checks](./tech_requirements/deployment.md) |
| Manual release sequence              | [deployment.md](./tech_requirements/deployment.md)               |


---

## Related docs


| Doc                                                          | Role                   |
| ------------------------------------------------------------ | ---------------------- |
| [cjm.md](./functional_requirements/cjm.md)                   | User journeys          |
| [skills/README.md](../skills/README.md)                      | Agent pedagogy IP      |
| [tech_requirements/README.md](./tech_requirements/README.md) | Locked stack index     |
| [backend.md](./tech_requirements/backend.md)                 | Service behavior       |
| [database.md](./tech_requirements/database.md)               | Entity design          |
| [ai-api.md](./tech_requirements/ai-api.md)                   | Gemini orchestration   |
| [frontend.md](./tech_requirements/frontend.md)               | UI routes              |
| [deployment.md](./tech_requirements/deployment.md)           | **Post-local** release |
| [hosting.md](./tech_requirements/hosting.md)                 | **Post-local** vendors |


