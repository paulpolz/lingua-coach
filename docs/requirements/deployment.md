# Deployment requirements

Status: **locked** (interview)

## Purpose

Define how the app is built, configured, migrated, and released for `local` and `prod`. Hosting vendors live in [hosting.md](./hosting.md); this doc covers process and runtime shape.

## Runtime shape (MVP)

| Process | Role |
|---------|------|
| Next.js | Frontend + Clerk-integrated UI |
| FastAPI | API, SSE chat, in-process today’s-focus jobs |
| PostgreSQL | System of record |
| Clerk | Hosted auth (SaaS; not self-deployed) |

No separate worker process in MVP (jobs run inside the API process). **Single API instance** until a durable job queue exists.

## Environments

| Env | Use |
|-----|-----|
| `local` | Developer machines |
| `prod` | Single production deployment |

No staging environment required for MVP.

## Configuration

All secrets and environment-specific values via env vars (or host secret store), including:

- `DATABASE_URL`
- Clerk secret / publishable keys (frontend + backend as appropriate)
- `GEMINI_API_KEY`, `GEMINI_MODEL_CHAT`, `GEMINI_MODEL_LESSON`
- `CORS_ORIGINS` / frontend URL
- `APP_ENV=local|prod`

Never commit `.env` with secrets. Provide `.env.example` with placeholder names only.

## Build & release (MVP)

**Manual deploy** to prod (CLI or hosting dashboard). No automatic deploy-on-merge.

Typical release sequence:

1. Run **Alembic migrations as an explicit step** before/with API release (not auto-migrate on API startup)
2. Build Next.js for production
3. Run FastAPI with a production ASGI server (e.g. Uvicorn/Gunicorn)
4. Deploy frontend and API (split or same platform — see hosting)
5. Smoke-verify (below)

### Smoke checks after prod promote

- `GET /health` OK
- Clerk sign-in works (prod Clerk instance + redirect URLs)
- One today’s-focus job completes; daily limit enforced
- One SSE chat turn streams tokens
- Gemini key present; focus/lesson JSON validates

## Local developer workflow

- **Docker Compose for Postgres** recommended
- Frontend + API runnable with hot reload
- Document short setup steps in repo root when implementation starts

## Observability (MVP)

| Item | MVP |
|------|-----|
| Structured logs to stdout | Required |
| `GET /health` on API | Required |
| Sentry / APM | **Not required** for first ship |

## CI (MVP baseline)

- Lint / typecheck / test on PRs when code exists
- **No CD to prod** on day one — manual deploy only
- Prefer reproducible builds (lockfiles)

## Constraints from product architecture

- **SSE:** platform/proxy must allow streaming responses and sufficient timeouts for chat
- **In-process jobs:** do not scale API to multiple replicas for MVP (job loss/duplication risk)
- **Clerk:** configure allowed origins / redirect URLs per environment

## Out of scope (MVP)

- Staging environment
- Auto-migrate on boot
- Full continuous deployment
- Blue/green or multi-region
- Separate async worker fleet
- Kubernetes as a requirement
- Mandatory error-tracking SaaS on day one

## Dependencies

- [backend.md](./backend.md), [frontend.md](./frontend.md), [database.md](./database.md), [ai-api.md](./ai-api.md)
- Concrete vendors in [hosting.md](./hosting.md)
