# Lingua Coach — Agent Skills

Generic, goal-agnostic skills for the learning engine. Prompt modules and system instructions that define **what the agent does** — separate from how the platform persists and renders it ([database.md](../docs/tech_requirements/database.md), [frontend.md](../docs/tech_requirements/frontend.md)).

## MVP vs post-MVP

| Skill | MVP | Role |
|-------|-----|------|
| [onboarding_interviewer.md](./onboarding_interviewer.md) | **Yes** | Discovery interview → learner profile |
| [course_composer.md](./course_composer.md) | **Yes** | Profile → roadmap, weekly template, plan days |
| [exercise_tutor.md](./exercise_tutor.md) | **Yes** | Lesson generation, in-chat coaching, error capture, session summary |
| [vocabulary_practice_formats.md](./vocabulary_practice_formats.md) | **Yes** | Weekly deep-review formats (A/B); used inside lesson chat |
| [feedback_giver.md](./feedback_giver.md) | **No** | Progress dashboard, weekly gates, structured feedback, plan adjustments |

## Pipeline

**MVP:**

```
onboarding_interviewer → course_composer → exercise_tutor
                                                │
                    pace hints + mistakes + session summaries (Postgres)
```

**Post-MVP** (adds closed-loop progress analysis):

```
exercise_tutor ──session summary──► feedback_giver ──► exercise_tutor / course_composer
```

## Agent responsibilities

The backend learning engine loads these skills as system instructions / prompt modules. The agent:

1. **Interacts** with the learner in chat (onboarding + lessons)
2. **Plans** the education program (`course_composer` → accepted roadmap)
3. **Conducts** lessons (`exercise_tutor`)
4. **Tracks** session outcomes, mistakes, and pace (`exercise_tutor` artifacts in MVP; `feedback_giver` enrichment post-MVP)
5. **Gives feedback** — inline in lesson chat in MVP; structured progress updates and weekly gates post-MVP (`feedback_giver`)

All structured outputs are **persisted to Postgres** — not inferred from chat history alone.

## Design principles

- **Goal-first, not curriculum-first** — the learner's outcome drives structure.
- **Adapt but never lower the goal** — pace adjusts; target outcome does not.
- **Output-first** — speak/write before (or alongside) rule explanation.
- **Structured learner memory** — profile, errors, and progress are data, not chat history.
- **Text chat in MVP** — all learner–tutor interaction is typed text; speaking/listening are practiced in text until voice ships.
- **Fixed ritual, personalized content** — daily shape stays constant; topics adapt to performance.

## Related docs

| Doc | Role |
|-----|------|
| [database.md](../docs/tech_requirements/database.md) | What each skill persists |
| [backend.md](../docs/tech_requirements/backend.md) | Orchestration and API lifecycle |
| [ai-api.md](../docs/tech_requirements/ai-api.md) | Gemini call types per skill |
| [frontend.md](../docs/tech_requirements/frontend.md) | UI surfaces for MVP skill use cases |
| [cjm.md](../docs/functional_requirements/cjm.md) | User journeys |

Backend reads skills at deploy time (e.g. copy or symlink into `prompts/`).
