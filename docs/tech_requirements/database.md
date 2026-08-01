# Database requirements

Status: **locked** (interview)

## Purpose

PostgreSQL is the system of record for users, learner knowledge, lessons, jobs, progress, mistakes, and chat. Store **structured knowledge about the learner**, not only conversation transcripts.

**Agent skills** ([skills/](../../skills/README.md)) define what artifacts each phase produces; this schema is the persistence contract for those outputs.

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
7. **Accepted course roadmap** is stored as JSONB on `learning_plans` — chat draft until accept; see [course_composer.md](../../skills/course_composer.md)
8. **Lesson chat produces artifacts, not a second curriculum store** — persist distilled JSON to `lessons.payload` and `mistakes`; `chat_messages` holds the live transcript until accept/finish, then is deleted
9. **Skills are the source of truth for artifact shapes** — MVP skills: `onboarding_interviewer`, `course_composer`, `exercise_tutor`; `feedback_giver` is post-MVP

## MVP entities

### `users`

- `id` (internal UUID)
- `clerk_user_id` (unique)
- `email` (optional cache from Clerk)
- `onboarding_complete` (boolean, default false)
- `plan_accepted_at` (nullable timestamp)
- `created_at`, `updated_at`

### `profiles` (1:1 with user)

Canonical store for **onboarding interviewer output** ([onboarding_interviewer.md](../../skills/onboarding_interviewer.md)). Written when the interview phase completes (before plan acceptance); schedule fields are filled on plan accept.

| Column | Type | Source (`learner_profile`) |
|--------|------|----------------------------|
| `user_id` | UUID FK, unique | — |
| `goal_outcome` | text | `goal.outcome` |
| `goal_horizon` | text | `goal.horizon` |
| `goal_success_criteria` | JSONB (string array) | `goal.success_criteria` |
| `english_level` | text | `level.self_assessed` (CEFR-ish or free text) |
| `level_strengths` | JSONB (string array) | `level.strengths` |
| `level_weaknesses` | JSONB (string array) | `level.weaknesses` |
| `diagnostic_notes` | text, nullable | `level.diagnostic_notes` |
| `time_budget` | JSONB | `time_budget.*` — see shape below |
| `focus` | JSONB | `focus.*` — see shape below |
| `constraints` | JSONB | `constraints.*` — see shape below |
| `motivation` | JSONB | `motivation.*` — see shape below |
| `interview_completed_at` | timestamp, nullable | set when onboarding chat persists profile |
| `grammar_mastery` | JSONB | runtime progress map (empty at interview; light updates from lesson `session_summary` in MVP; full scoring post-MVP via `feedback_giver`) |
| `vocabulary_summary` | JSONB | runtime progress map (empty at interview; themes from `session_summary` in MVP) |
| `confidence_flags` | JSONB | runtime progress map (empty at interview; post-MVP via `feedback_giver`) |
| `target_plan_days` | integer, nullable | denormalized from `learning_plans.roadmap.summary.target_plan_days` on accept |
| `active_learning_plan_id` | UUID FK, nullable | → `learning_plans.id` (current accepted roadmap) |
| `projected_completion_at` | timestamp, nullable | derived at accept; recomputed on finish, reschedule, plan updates |
| `plan_slip_days` | integer, default 0 | cumulative slip when lessons finish after pace window |
| `pace_window_hours` | integer, default **24** | on-pace threshold from `started_at` to `accomplished_at` |
| `created_at`, `updated_at` | timestamps | — |

**JSON shapes (onboarding):**

```json
"time_budget": {
  "minutes_per_session": 60,
  "sessions_per_week": 5,
  "optional_partner_minutes": 30,
  "intensity": "sustainable"
}
"focus": {
  "skill_priorities": ["speaking", "grammar", "listening"],
  "topic_priorities": ["work emails", "meetings"],
  "avoid": []
}
"constraints": {
  "budget": "none",
  "practice_partner": { "available": true, "minutes": 30, "relationship": "spouse" },
  "learning_style": "correction-heavy"
}
"motivation": {
  "why_now": "...",
  "past_blockers": ["..."]
}
```

**Persistence timing:**

| Event | What is written |
|-------|-----------------|
| Onboarding interview complete | All interview columns above → `profiles`; draft row → `learning_goals` |
| Plan accepted (`POST /onboarding/accept`) | `learning_plans` row (`roadmap` JSONB, `status = accepted`); `profiles.active_learning_plan_id`, `target_plan_days`, initial `projected_completion_at`; `users.onboarding_complete`, `users.plan_accepted_at`; `learning_goals.status = active` |
| Lesson / chat feedback | `mistakes`, `lessons.payload.session_summary`, `progress_events`; optional light patch to profile progress JSON maps; `plan_updates` may patch `learning_plans.roadmap` and schedule fields |
| Lesson becomes **active** | `lessons.payload.curriculum` — structure, themes, exercise-set descriptions ([exercise_tutor.md](../../skills/exercise_tutor.md)) |
| Mid-lesson (pattern logged) | Upsert **`mistakes`** — `pattern_type` + short `example_text` |
| Lesson **accomplished** | `lessons.payload.session_summary`; `lesson_completed` → `progress_events`; pace fields on `lessons` / `profiles` |

**Plan day ≡ accomplished lesson:** `lesson_number` of accomplished lessons = plan days completed toward `target_plan_days`. No calendar-day assignment.

`onboarding_complete` lives on **`users`**, not `profiles` — interview output can exist while the plan is still a draft.

### `learning_goals`

Draft created when onboarding interview persists; activated on plan accept.

| Column | Type | Source |
|--------|------|--------|
| `id` | UUID | — |
| `user_id` | UUID FK | — |
| `goal_statement` | text | `goal.outcome` (denormalized from `profiles` for query convenience) |
| `horizon` | text, nullable | `goal.horizon` |
| `success_criteria` | JSONB | `goal.success_criteria` |
| `status` | enum | `draft` (after interview) → `active` (on accept) → `archived` |
| `created_at`, `updated_at` | timestamps | — |

- MVP: one **`active`** (or **`draft`**) goal per user — enforce in app; optional partial unique index later
- Full course structure lives on **`learning_plans.roadmap`**; `target_plan_days` and projection are denormalized on **`profiles`** for pace queries

### `learning_plans`

Canonical store for **accepted course roadmap** ([course_composer.md](../../skills/course_composer.md)). Draft roadmap exists only in onboarding chat until accept — not persisted as a separate row in MVP.

| Column | Type | Source / notes |
|--------|------|----------------|
| `id` | UUID | — |
| `user_id` | UUID FK | — |
| `learning_goal_id` | UUID FK | linked goal |
| `status` | enum | `accepted` \| `superseded` |
| `roadmap` | JSONB | full `course_roadmap` — see schema below |
| `current_milestone_index` | integer | copied from `roadmap.current_milestone_index`; updated on milestone pass |
| `accepted_at` | timestamp | set on `POST /onboarding/accept` |
| `superseded_at` | timestamp, nullable | set when a replan replaces this row |
| `created_at`, `updated_at` | timestamps | — |

**MVP:** one **`accepted`** plan per user (enforce in app). Replan: mark old row `superseded`, insert new `accepted` row, update `profiles.active_learning_plan_id`.

**`roadmap` JSON shape (`course_roadmap`, version 1):**

```json
{
  "version": 1,
  "summary": {
    "goal_outcome": "string",
    "goal_horizon": "string",
    "starting_level": "string",
    "target_plan_days": 90,
    "target_plan_days_range": [80, 100],
    "pace_description": "string"
  },
  "milestones": [
    {
      "index": 0,
      "title": "string",
      "skill_developed": "string",
      "why_now": "string",
      "connects_to": [0],
      "success_criteria": "string",
      "estimated_plan_days": 5
    }
  ],
  "weekly_template": {
    "minutes_per_session": 60,
    "activities": [
      { "id": "warmup", "label": "string", "minutes": 5 }
    ],
    "partner_session": null,
    "weekends": "string"
  },
  "current_block": {
    "milestone_index": 0,
    "weeks": 1,
    "focus_summary": "string",
    "themes": [
      {
        "block_day": 1,
        "grammar_focus": "string",
        "vocab_theme": "string",
        "input_type": "listening",
        "production_focus": "string",
        "goal_specific_focus": "string"
      }
    ]
  },
  "learning_principles": ["active_recall", "spaced_repetition"],
  "adaptation_rules": {
    "failed_weekly_test": "repeat_milestone_content",
    "recurring_error_pattern": "inject_retrieval_drill",
    "strong_performance": "increase_difficulty_not_shorten_goal",
    "user_feedback": "adjust_next_1_2_weeks_focus"
  },
  "current_milestone_index": 0
}
```

Validate against Pydantic before insert/update. `exercise_tutor` and lesson generation read **`learning_plans.roadmap`** + learner profile — not chat history.

### `jobs`

- `id`, `user_id`, `type` (e.g. `lesson_generate`)
- `status`: `pending` | `running` | `done` | `failed`
- `error` (nullable)
- `result_ref` (e.g. `lesson_id`)
- timestamps

### `lessons`

Canonical store for **lesson curriculum + session outcome** ([exercise_tutor.md](../../skills/exercise_tutor.md)). Chat delivers exercises and coaching; **`payload` JSONB** is what the next lesson reads — not `chat_messages`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | — |
| `user_id` | UUID FK | — |
| `learning_goal_id` | UUID FK, nullable | goal active when lesson started |
| `learning_plan_id` | UUID FK, nullable | roadmap version active when lesson started |
| `lesson_number` | integer | 1-based, sequential per user |
| `payload` | JSONB | `curriculum` at active; `session_summary` at accomplish — see shape below |
| `status` | enum | `generating` \| `active` \| `accomplished` \| `failed` |
| `started_at` | timestamp, nullable | set when status → **`active`** (24h pace window starts) |
| `accomplished_at` | timestamp, nullable | set on finish |
| `pace_status` | enum, nullable | `on_pace` \| `slipped` — at finish if `accomplished_at - started_at > pace_window_hours` |
| `created_at`, `updated_at` | timestamps | — |

- **Unique constraint:** `(user_id, lesson_number)`
- **App rule:** at most one row per user with status in (`generating`, `active`)
- Lessons are created **on demand** when the user starts — not in advance, not by calendar date
- Validate `payload` against Pydantic before insert/update

**`payload` JSON shape (`lesson_record`, version 1):**

```json
{
  "version": 1,
  "curriculum": {
    "lesson_goal": "string",
    "grammar_focus": "string",
    "vocab_theme": "string",
    "milestone_index": 0,
    "slots": [
      {
        "id": "warmup",
        "label": "string",
        "exercise_set": "Brief description of planned drills — not full chat scripts"
      }
    ],
    "input_task": { "type": "listening | reading", "topic": "string", "focus": "string" },
    "goal_specific_task": { "label": "string", "format": "string" },
    "exit_criteria": ["string"],
    "partner_session": null
  },
  "session_summary": {
    "duration_minutes": 45,
    "completed_slots": ["warmup", "production"],
    "deferred_items": [{ "slot_id": "input", "reason": "time" }],
    "exit_criteria_met": true,
    "performance_notes": "string",
    "focus_pattern_result": {
      "grammar_focus": "string",
      "met": true,
      "note": "string"
    },
    "resolved_pattern_types": ["string"],
    "new_pattern_types": ["string"],
    "vocab_themes_covered": ["string"],
    "learner_feedback": "string"
  }
}
```

- **`curriculum`** — written when the lesson becomes **`active`** (after generation job succeeds)
- **`session_summary`** — `null` until accomplish; then required before status → **`accomplished`**
- Do **not** store per-message dialogue, full vocab lists, or every learner utterance in `payload`

**Prior-lesson context for generation:** last **N** accomplished lessons — inject `payload.curriculum` + `payload.session_summary` only, not chat history.

### `progress_events`

- User FK, optional lesson / session FKs
- Event type (e.g. `lesson_completed`, exercise result, `plan_updated`, `plan_rescheduled`)
- Payload JSON + `created_at`

### `mistakes`

Canonical store for **recurring error patterns** extracted during lesson chat ([exercise_tutor.md](../../skills/exercise_tutor.md)). One row per named pattern occurrence log — not every chat correction.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | — |
| `user_id` | UUID FK | — |
| `lesson_id` | UUID FK, nullable | lesson where pattern was last seen / logged |
| `pattern_type` | text | taxonomy label, e.g. `missing articles`, `irregular past` |
| `example_text` | text | short learner span or sentence (one example) |
| `correction` | text, nullable | one-line correct form (optional) |
| `occurrence_count` | integer, default 1 | increment on repeat of same pattern |
| `next_review_at` | timestamp, nullable | spaced repetition (+1, +3, +7, +14 days) |
| `last_seen_at` | timestamp | most recent log |
| `created_at` | timestamp | first log |

- **Upsert rule (app):** same `user_id` + `pattern_type` → increment `occurrence_count`, refresh `example_text` / `lesson_id` / `last_seen_at`, recompute `next_review_at` on failure
- Supports dashboard summaries, warm-up injection, and future analysis
- Full correction dialogue stays in **`chat_messages`** only

**MVP-light JSON emitted by tutor (before backend enrich):**

```json
{
  "pattern_type": "missing articles",
  "example_text": "I went to store yesterday"
}
```

### Vocabulary (MVP-light)

- No full vocabulary dimension table required
- Track via `profiles` JSON and/or fields inside mistake/progress payloads

### Chat

- `chat_sessions` — user FK, optional lesson FK, **`type`**: `onboarding` | `lesson`; **one session per onboarding and one per lesson**
- `chat_messages` — session FK, role, content, `created_at`, optional metadata JSON

**Chat vs artifacts:** `chat_messages` holds the live conversation for UI resume (load from backend on every visit — do not rely on client cache). **`lessons.payload`** and **`mistakes`** hold distilled knowledge for the next lesson. Do not rebuild lesson context from unbounded chat history.

**Retention:** keep messages for the duration of the conversation only. **Delete** onboarding messages (and session) on `POST /onboarding/accept`; delete lesson messages (and session) on `POST /lessons/{id}/finish`. Artifacts in `profiles`, `learning_plans`, `lessons.payload`, and `mistakes` are the long-term store.

### Deferred (post-MVP — `feedback_giver`)

- Progress dashboard rows (skill categories, progress %, weaknesses, recommendations)
- Error log update log and open-items queue (beyond `session_summary.deferred_items`)
- Weekly assessment session records and milestone gate results
- Automated structural replan triggers driven by test failure / stuck readiness
- Skill component scores (reading, listening, speaking, writing) as first-class tables
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
| History | Prior **`lessons.payload`** summaries + **`mistakes`** + `progress_events` feed generation prompts — not full chat transcripts |

## Plan schedule rules

| Rule | Detail |
|------|--------|
| Target | `target_plan_days` set at accept from `learning_plans.roadmap.summary` |
| Roadmap | Full structure in `learning_plans.roadmap`; patches via chat `plan_updates` |
| Projection | Initial `projected_completion_at` ≈ now + remaining plan days × 24h at ideal pace (implementation may use calendar-day rounding for display) |
| Reschedule | On slipped finish: increment `plan_slip_days` by 1; extend `projected_completion_at`; emit `plan_rescheduled` |
| Chat updates | `plan_updates` may change `target_plan_days` → recompute projection |
| Not calendar | No rows for “lesson on date X”; sequential on-demand only |

## Indexes (MVP)

- `users.clerk_user_id` unique
- `profiles.user_id` unique
- `learning_goals (user_id)` where status in (`draft`, `active`) — optional partial unique for one open goal
- `learning_plans (user_id)` where status = `accepted` — optional partial unique for one active roadmap
- `lessons (user_id, lesson_number)` unique
- `lessons (user_id)` where status in active states — for fast active-lesson lookup
- `jobs (user_id, created_at)`
- `progress_events (user_id, created_at)`
- `mistakes (user_id, created_at)`
- `chat_messages (session_id, created_at)`

## Data lifecycle

| Data | MVP policy |
|------|------------|
| Users, profiles, goals, lessons, progress, mistakes | **Retain indefinitely** |
| Jobs | **Retain** (debugging); no TTL in MVP |
| Chat sessions + messages | **Delete on onboarding accept or lesson finish** — artifacts only after that |
| Soft delete | **Not required** for MVP |

## Security

- No API keys or Clerk secrets in DB
- Row-level access always scoped by authenticated `user_id` in the API layer
- Migrations checked into repo; prod credentials via env (`DATABASE_URL`)

## Onboarding data flow

```
onboarding chat (type=onboarding)
    → AI emits learner_profile → upsert profiles + learning_goals (draft)
    → course_composer presents course roadmap in chat (draft)
    → user refines roadmap in same chat
    → POST /onboarding/accept { session_id, course_roadmap }
    → insert learning_plans (roadmap JSONB, accepted)
    → profiles.active_learning_plan_id, target_plan_days, projected_completion_at
    → users.onboarding_complete, learning_goals.status=active
    → delete onboarding chat_messages + chat_session
```

Chat transcript is **not** the source of truth — `profiles` (learner facts) and `learning_plans.roadmap` (accepted course structure) are.

## Lesson data flow

```
POST /lessons/start
    → job generates curriculum → lessons row (status generating → active)
    → lessons.payload.curriculum persisted; started_at set
    → lesson chat session opened

lesson chat (type=lesson) — exercise_tutor skill
    → tutor coaches in chat_messages (exercises, explain, review, motivate)
    → on recurring error → upsert mistakes (pattern_type + example_text)
    → on finish → lessons.payload.session_summary persisted
    → status accomplished; lesson_completed progress_event
    → pace evaluation on profiles (24h rule); optional light progress JSON patch
    → delete lesson chat_messages + chat_session

next POST /lessons/start
    → inject prior lessons.payload (curriculum + session_summary) + open mistakes
    → not full prior chat history

(post-MVP: feedback_giver reads payload + mistakes → progress dashboard, weekly gates, replans)
```

## Skill → table mapping (MVP)

| Skill | Reads | Writes |
|-------|-------|--------|
| `onboarding_interviewer` | — | `profiles`, `learning_goals` (draft), `chat_messages` |
| `course_composer` | `profiles` | `learning_plans.roadmap` (on accept), `chat_messages` |
| `exercise_tutor` | `profiles`, `learning_plans`, prior `lessons.payload`, `mistakes` | `lessons.payload`, `mistakes`, `progress_events`, `chat_messages` |
| `vocabulary_practice_formats` | (within lesson) | slots in `lessons.payload.curriculum` / chat only |

## Dependencies

- Written by [backend.md](./backend.md)
- Profile shape consumed by [ai-api.md](./ai-api.md)
- Agent skills: [skills/README.md](../../skills/README.md)
- Onboarding output schema: [onboarding_interviewer.md](../../skills/onboarding_interviewer.md)
- Course roadmap schema: [course_composer.md](../../skills/course_composer.md)
- Lesson artifacts: [exercise_tutor.md](../../skills/exercise_tutor.md)
- Post-MVP progress: [feedback_giver.md](../../skills/feedback_giver.md)
- Journeys in [cjm.md](../functional_requirements/cjm.md)
- Hosted per [hosting.md](./hosting.md)
