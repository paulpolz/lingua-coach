# Database requirements

Status: **locked** (interview)

## Purpose

PostgreSQL is the system of record for users, learner knowledge, lessons, jobs, progress, mistakes, and chat. Store **structured knowledge about the learner**, not only conversation transcripts.

## Stack

| Item | Choice |
|------|--------|
| Engine | **PostgreSQL** |
| ORM | **SQLAlchemy 2.x** |
| Migrations | **Alembic** |
| Auth sessions | **Not stored here** — Clerk owns sessions; we store `clerk_user_id` |

## Design principles

1. Every authenticated Clerk user maps to exactly one `users` row (upsert on first API use)
2. Learner profile fields are first-class columns/JSON — not inferred only from chat logs
3. Schema depth is **medium**: dedicated tables for goals, progress events, and mistakes; vocabulary stays light/JSON
4. Lesson jobs are durable enough for polling (`pending` → `running` → `done`/`failed`) even with in-process workers
5. Enforce **1 lesson per day (UTC)** with an application check **and** a DB unique constraint

## MVP entities

### `users`

- `id` (internal UUID)
- `clerk_user_id` (unique)
- `email` (optional cache from Clerk)
- `created_at`, `updated_at`

### `profiles` (1:1 with user)

- Target / goal summary text (may mirror active learning goal)
- English level (e.g. CEFR-ish)
- Preferred lesson length
- Lightweight motivation / learning-style notes
- Structured maps as JSON: grammar mastery, vocabulary summary, confidence flags

### `learning_goals`

- User FK
- Goal statement, optional target date, status (`active` / `archived`)
- MVP: one active goal per user is sufficient (enforce in app; optional partial unique index later)

### `jobs`

- `id`, `user_id`, `type` (e.g. `lesson_generate`)
- `status`: `pending` | `running` | `done` | `failed`
- `error` (nullable)
- `result_ref` (e.g. `lesson_id`)
- timestamps

### `lessons`

- User FK, optional `learning_goal_id`
- Structured payload (JSON matching AI lesson schema)
- `lesson_date` (**UTC date**) used for daily-limit checks
- Status as needed: `ready` / `consumed` / `abandoned`
- **Unique constraint:** `(user_id, lesson_date)`

### `progress_events`

- User FK, optional lesson / session FKs
- Event type (e.g. lesson completed, exercise result)
- Payload JSON + `created_at`

### `mistakes`

- User FK, optional lesson / message FKs
- Taxonomy fields: type, span/text, note
- `created_at`
- Supports progress UI and future profile score updates

### Vocabulary (MVP-light)

- No full vocabulary dimension table required
- Track via `profiles` JSON and/or fields inside mistake/progress payloads

### Chat

- `chat_sessions` — user FK, optional lesson FK
- `chat_messages` — session FK, role, content, `created_at`, optional metadata JSON

### Deferred (post-MVP)

- Achievements
- Weekly reports
- Full vocabulary / grammar topic dimension tables

## Daily lesson limit

| Rule | Detail |
|------|--------|
| Cap | At most **one** lesson row per user per **UTC** calendar date |
| App | Check before starting `POST /lessons/today`; return a clear “already used today” error |
| DB | Unique `(user_id, lesson_date)` as safety net against double submit |
| Timezone | UTC only in MVP — no per-user timezone for limit calculation |

## Indexes (MVP)

- `users.clerk_user_id` unique
- `lessons (user_id, lesson_date)` unique
- `jobs (user_id, created_at)`
- `progress_events (user_id, created_at)`
- `mistakes (user_id, created_at)`
- `chat_messages (session_id, created_at)`

## Data lifecycle

| Data | MVP policy |
|------|------------|
| Users, profiles, goals, lessons, progress, mistakes, chat | **Retain indefinitely** |
| Jobs | **Retain** (debugging); no TTL in MVP |
| Soft delete | **Not required** for MVP |

## Security

- No API keys or Clerk secrets in DB
- Row-level access always scoped by authenticated `user_id` in the API layer
- Migrations checked into repo; prod credentials via env (`DATABASE_URL`)

## Dependencies

- Written by [backend.md](./backend.md)
- Profile shape consumed by [ai-api.md](./ai-api.md)
- Hosted per [hosting.md](./hosting.md)
