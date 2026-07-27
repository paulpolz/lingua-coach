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
5. Lessons are **sequential integers** per user — not calendar-dated; **at most one in-flight lesson** (`generating` or `active`) enforced in app (partial unique index optional)
6. **Plan schedule** is stored as structured fields (target plan days, projection, slip) — not as calendar lesson slots

## MVP entities

### `users`

- `id` (internal UUID)
- `clerk_user_id` (unique)
- `email` (optional cache from Clerk)
- `onboarding_complete` (boolean, default false)
- `plan_accepted_at` (nullable timestamp)
- `created_at`, `updated_at`

### `profiles` (1:1 with user)

- **Goal** summary text (why + outcome / horizon)
- English level (e.g. CEFR-ish)
- **Time budget** (practice cadence + intensity / pace — JSON or columns)
- Topics / vocab priorities (JSON)
- Structured maps as JSON: grammar mastery, vocabulary summary, confidence flags
- **Schedule (plan pacing):**
  - `target_plan_days` (integer) — estimated accomplished lessons to reach goal; set at onboarding accept; updatable via chat `plan_updates`
  - `projected_completion_at` (timestamp) — derived from target, pace, and slip; recomputed on accept, finish, reschedule, and material plan changes
  - `plan_slip_days` (integer, default 0) — cumulative slip when lessons finish after the 24h window
  - `pace_window_hours` (integer, default **24**) — on-pace threshold from lesson `started_at` to `accomplished_at`

**Plan day ≡ accomplished lesson:** `lesson_number` of accomplished lessons = plan days completed toward `target_plan_days`. No calendar-day assignment.

### `learning_goals`

- User FK
- Goal statement, optional target date (horizon hint for projection), status (`active` / `archived`)
- MVP: one active goal per user is sufficient (enforce in app; optional partial unique index later)
- May mirror or reference `target_plan_days` from profile; single source of truth should be profile schedule fields unless denormalized for queries

### `jobs`

- `id`, `user_id`, `type` (e.g. `lesson_generate`)
- `status`: `pending` | `running` | `done` | `failed`
- `error` (nullable)
- `result_ref` (e.g. `lesson_id`)
- timestamps

### `lessons`

- User FK, optional `learning_goal_id`
- **`lesson_number`** (integer, 1-based, sequential per user)
- Structured payload (JSON matching AI lesson schema)
- **Status:** `generating` | `active` | `accomplished` | `failed`
- `started_at` — set when lesson becomes **`active`** (start of 24h pace window)
- `accomplished_at` (nullable) — set on finish; used with `started_at` for on-pace / slip
- Optional on lesson row: `pace_status` (`on_pace` | `slipped`) — set at finish when `accomplished_at - started_at > pace_window_hours`
- **Unique constraint:** `(user_id, lesson_number)`
- **App rule:** at most one row per user with status in (`generating`, `active`)

Lessons are created **on demand** when the user starts — not in advance, not by calendar date.

### `progress_events`

- User FK, optional lesson / session FKs
- Event type (e.g. `lesson_completed`, exercise result, `plan_updated`, `plan_rescheduled`)
- Payload JSON + `created_at`

### `mistakes`

- User FK, optional lesson / message FKs
- Taxonomy fields: type, span/text, note
- `created_at`
- Supports dashboard summaries and future analysis features

### Vocabulary (MVP-light)

- No full vocabulary dimension table required
- Track via `profiles` JSON and/or fields inside mistake/progress payloads

### Chat

- `chat_sessions` — user FK, optional lesson FK, **`type`**: `onboarding` | `lesson`
- `chat_messages` — session FK, role, content, `created_at`, optional metadata JSON

### Deferred (post-MVP)

- Skill component scores (reading, listening, speaking, writing)
- Achievements
- Weekly reports
- Full vocabulary / grammar topic dimension tables
- Analysis / time-to-goal materialized views (MVP uses `projected_completion_at` + dashboard hints only)

## Lesson sequencing rules

| Rule | Detail |
|------|--------|
| Numbering | `lesson_number` starts at 1; each new start uses `MAX(lesson_number) + 1` |
| Plan day | Accomplished `lesson_number` = plan days completed |
| In-flight cap | Only one `generating` or `active` lesson per user |
| Start gate | `POST /lessons/start` rejected if a generating/active lesson exists |
| Next lesson | Allowed only after current lesson is `accomplished` |
| Pace window | On finish: if `accomplished_at - started_at` ≤ 24h → on pace; else increment `plan_slip_days` and recompute `projected_completion_at` |
| History | Prior lessons + mistakes + progress feed generation prompts |

## Plan schedule rules

| Rule | Detail |
|------|--------|
| Target | `target_plan_days` set at onboarding accept (from AI + user time budget) |
| Projection | Initial `projected_completion_at` ≈ now + remaining plan days × 24h at ideal pace (implementation may use calendar-day rounding for display) |
| Reschedule | On slipped finish: increment `plan_slip_days` by 1; extend `projected_completion_at`; emit `plan_rescheduled` |
| Chat updates | `plan_updates` may change `target_plan_days` → recompute projection |
| Not calendar | No rows for “lesson on date X”; sequential on-demand only |

## Indexes (MVP)

- `users.clerk_user_id` unique
- `lessons (user_id, lesson_number)` unique
- `lessons (user_id)` where status in active states — for fast active-lesson lookup
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
- Journeys in [cjm.md](../functional_requirements/cjm.md)
- Hosted per [hosting.md](./hosting.md)
