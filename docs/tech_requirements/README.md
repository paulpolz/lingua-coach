# Requirements index

Tech requirements split from the product [README](../../README.md). All six areas below are **interview-locked**.

Functional journeys: [cjm.md](../functional_requirements/cjm.md).

**Local MVP gate:** [implementation-readiness.md](../implementation-readiness.md) — local setup, env vars, API/SSE contracts, build order, smoke tests. Production deploy deferred to [deployment.md](./deployment.md) / [hosting.md](./hosting.md).

| Document | Covers |
|----------|--------|
| [backend.md](./backend.md) | FastAPI, Clerk, REST+SSE, sequential on-demand lessons, plan schedule & 24h pacing |
| [ai-api.md](./ai-api.md) | Gemini-only LLM layer, onboarding + lesson chat, prior-lesson-aware generation |
| [database.md](./database.md) | Postgres, SQLAlchemy+Alembic, sequential `lesson_number`, one active lesson |
| [frontend.md](./frontend.md) | Next.js+shadcn+Clerk, chat-first onboarding + practice, no plan editor |
| [deployment.md](./deployment.md) | local+prod, manual deploy, explicit Alembic, logs+health |
| [hosting.md](./hosting.md) | Vercel + Railway + Cloudflare domain, Clerk, Gemini; trial then ~$5/mo |
