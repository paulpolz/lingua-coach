# Requirements index

Tech requirements split from the product [README](../../README.md). All areas below are **interview-locked**.

Functional journeys: [cjm.md](../functional_requirements/cjm.md).

**Agent skills (pedagogy IP):** [skills/](../../skills/README.md) at repo root — source of truth for agent behavior. Tech docs below define persistence, API, and UI contracts for those skills.

**Local MVP gate:** [implementation-readiness.md](../implementation-readiness.md) — local setup, env vars, API/SSE contracts, build order, smoke tests. Production deploy deferred to [deployment.md](./deployment.md) / [hosting.md](./hosting.md).

| Document | Covers |
|----------|--------|
| [backend.md](./backend.md) | FastAPI, Clerk, REST+SSE, sequential on-demand lessons, plan schedule & 24h pacing |
| [ai-api.md](./ai-api.md) | Gemini-only LLM layer, skill-backed prompts, onboarding + lesson chat |
| [database.md](./database.md) | Postgres, SQLAlchemy+Alembic, artifacts per skill, one active lesson |
| [frontend.md](./frontend.md) | Next.js+shadcn+Clerk, chat-first UI for all MVP skill use cases |
| [deployment.md](./deployment.md) | local+prod, manual deploy, explicit Alembic, logs+health |
| [hosting.md](./hosting.md) | Vercel + Railway + Cloudflare domain, Clerk, Gemini; trial then ~$5/mo |

## Agent architecture (summary)

```
skills/ (repo root)  →  backend learning engine  →  Gemini
                              ↓
                         PostgreSQL (artifacts)
                              ↓
                         Next.js (chat + dashboard)
```

| Skill | MVP | Persists | Frontend |
|-------|-----|----------|----------|
| `onboarding_interviewer` | Yes | `profiles`, draft `learning_goals` | Onboarding chat |
| `course_composer` | Yes | `learning_plans.roadmap` on accept | Plan in chat + accept action |
| `exercise_tutor` | Yes | `lessons.payload`, `mistakes`, `progress_events` | Lesson chat, start/resume/finish |
| `vocabulary_practice_formats` | Yes | (within lesson artifacts) | Delivered in lesson chat |
| `feedback_giver` | **No** | dashboard, weekly gates, replans (future) | Analysis / progress UI (future) |

See [skills/README.md](../../skills/README.md) for full skill definitions.
