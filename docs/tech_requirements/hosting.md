# Hosting

Lingua Coach runs from the Docker Compose stack in [deployment.md](./deployment.md). The repository contains no cloud hosting configuration: no Vercel project, Railway service, Terraform, or managed database setup.

## What runs where

```mermaid
flowchart LR
  subgraph machine [Your machine: docker compose]
    fe[frontend]
    be[backend]
    pg[(postgres)]
    mon[prometheus, loki, promtail, grafana]
  end
  subgraph external [External services]
    clerk[Clerk]
    gemini[Google Gemini API]
    langsmith[LangSmith: local and staging only]
  end
  fe --> clerk
  be --> clerk
  be --> gemini
  be -.->|LANGSMITH_TRACING| langsmith
  fe --> be
  be --> pg
  mon --> be
```

| Component | Runs in | Owner |
|-----------|---------|-------|
| Next.js frontend | Compose `frontend` (`next dev`) | This repo |
| FastAPI backend | Compose `backend` (`uvicorn --reload`) | This repo |
| PostgreSQL | Compose `postgres`, volume `lingua_pg_data` | This repo |
| Monitoring | Compose `prometheus`, `loki`, `promtail`, `grafana` (started with the app) | This repo |
| Authentication | Clerk (Development instance by default) | External, configured with Clerk keys |
| LLM | Google Gemini API | External, configured with `LLM_API_KEY` (`LLM_PROVIDER=google`) |
| LLM tracing and evals | LangSmith (smith.langchain.com) | External, local and staging only, configured with `LANGSMITH_*` |

## External accounts needed

- **Clerk**: an application with email sign-in. Copy the publishable key and secret key into both env files. With a Development instance, leaving `CLERK_JWT_ISSUER` empty is enough.
- **Google AI Studio**: a Gemini API key (`LLM_API_KEY`). Set the global backend limits (`LLM_RPM_LIMIT`, `LLM_INPUT_TPM_LIMIT`, `LLM_RPD_LIMIT`) to match the key's quota.
- **LangSmith** (optional): an API key and one project per environment (`lingua-coach-local`, `lingua-coach-staging`). The free Developer plan is enough at staging volume. Production never traces. CI evals need the `LANGSMITH_API_KEY` and `LLM_API_KEY` repository secrets.

## Moving off Compose

The containers are dev-oriented: both mount the source and run with reload. A hosted setup would need:

- a production frontend build (`npm run build` and `npm run start`);
- the backend image without `--reload` (its default `CMD` already serves on `${PORT:-8000}`);
- a managed Postgres reachable through `DATABASE_URL`, with `alembic upgrade head` run on deploy;
- `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`, and `API_URL` set to the public URLs;
- `APP_ENV=production` and a Clerk Production instance with `CLERK_JWT_ISSUER` set to its issuer (the app refuses to start outside `local` without it);
- `LANGSMITH_TRACING` unset or `false` (enforced in production);
- Prometheus able to reach `/metrics`, or `METRICS_ENABLED=false`.

## Environments

| Environment | Where | Data | Clerk | LangSmith |
|-------------|-------|------|-------|-----------|
| `local` | Compose on a developer machine | Developer's own | Development instance; issuer optional | Optional, project `lingua-coach-local` |
| `staging` | A hosted copy of the production setup (see [deployment.md](./deployment.md#staging)) | Its own database, test accounts only | Development instance, `CLERK_JWT_ISSUER` set | On, project `lingua-coach-staging` |
| `production` | Hosted | Real learners | Production instance, `CLERK_JWT_ISSUER` set | Off (startup check) |

No staging or production deployment is configured in this repository yet; the table is the required setup.
