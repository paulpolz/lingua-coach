# Deployment

The repository runs as one Docker Compose stack defined in [`docker-compose.yml`](../../../../docker-compose.yml).

## Services

```mermaid
flowchart TB
  subgraph app [default profile]
    pg[(postgres:16-alpine :5432)]
    be[backend :8000]
    fe[frontend :3000]
    be --> pg
    fe --> be
  end
  subgraph mon [profile: monitoring]
    prom[prometheus :9090]
    loki[loki :3100]
    promtail[promtail]
    graf[grafana :3001]
    prom -->|scrape /metrics| be
    promtail -->|docker.sock logs| loki
    graf --> prom
    graf --> loki
  end
```

| Service | Image / build | Port | Notes |
|---------|---------------|------|-------|
| `postgres` | `postgres:16-alpine` | 5432 | User, password `lingua`, database `lingua_coach`; volume `lingua_pg_data`; healthcheck `pg_isready` |
| `backend` | `apps/backend/Dockerfile` (Python 3.11, `uv`) | 8000 | Waits for a healthy Postgres, runs `alembic upgrade head`, then `uvicorn --reload`; source mounted at `/app` |
| `frontend` | `apps/frontend/Dockerfile` (Node 20) | 3000 | `next dev`; source mounted; `API_URL=http://backend:8000` for server components |
| `prometheus` | `prom/prometheus:v2.55.0` | 9090 | Config `infra/monitoring/prometheus.yml`, scrapes `backend:8000/metrics` every 15 s |
| `loki` | `grafana/loki:3.0.0` | 3100 | Single-process config `infra/monitoring/loki-config.yml` |
| `promtail` | `grafana/promtail:3.0.0` | none | Ships Docker container logs to Loki |
| `grafana` | `grafana/grafana:11.0.0` | 3001 | Admin `admin`/`admin`, anonymous viewer; provisioned datasources and dashboards |

Grafana dashboards in `infra/monitoring/grafana/provisioning/dashboards/json/`:

- **API Overview**: request rate, 4xx/5xx error rate, response codes, P95/P99 latency.
- **Errors & Correlation** (Loki): recent backend errors and warnings, failed `llm_call` lines, `db_persist_failed` lines, and a trace of every log line for one `request_id`.
- **LLM & Token Burn**: Gemini request rate, token burn rate, cumulative tokens, P95 latency, and errors by status.

## Run it

```bash
cp apps/backend/.env.example apps/backend/.env
cp apps/frontend/.env.example apps/frontend/.env.local
# fill in Clerk keys and GEMINI_API_KEY

docker compose up                         # app
docker compose --profile monitoring up    # app + monitoring
```

Open http://localhost:3000. The API is at http://localhost:8000, Prometheus at http://localhost:9090, and Grafana at http://localhost:3001.

Without Docker, start Postgres yourself, then:

```bash
cd apps/backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd apps/frontend && npm install && npm run dev
```

## Backend environment (`apps/backend/.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_ENV` | `local` | Environment label |
| `LOG_LEVEL` | `INFO` | JSON log level |
| `METRICS_ENABLED` | `true` | Expose `/metrics` |
| `DATABASE_URL` | local Postgres | `postgresql+asyncpg://…`; Compose overrides it with the `postgres` host |
| `CLERK_SECRET_KEY` | empty | Clerk backend key |
| `CLERK_JWT_ISSUER` | empty | Exact issuer; empty accepts `https://*.clerk.accounts.dev` |
| `GEMINI_API_KEY` | empty | Required for any coach reply |
| `GEMINI_MODEL_CHAT` | `gemini-3.5-flash-lite` | Chat model |
| `GEMINI_MODEL_LESSON` | `gemini-3.5-flash-lite` | Lesson and report JSON model |
| `GEMINI_TIMEOUT_SECONDS` | `120` | Per-call timeout |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `CHAT_RATE_LIMIT_PER_HOUR` | `60` | Per-user chat messages |
| `LESSON_START_RATE_LIMIT_PER_DAY` | `2` | Per-user lesson starts |
| `LLM_RPM_LIMIT` | `15` | Global Gemini requests per minute |
| `LLM_INPUT_TPM_LIMIT` | `250000` | Global Gemini input tokens per minute |
| `LLM_RPD_LIMIT` | `500` | Global Gemini requests per day |
| `MAX_MESSAGE_CHARS` | `4000` | Longest learner message |
| `CHAT_CONTEXT_MESSAGES` | `10` | Turns sent to Gemini per chat call |
| `PACE_WINDOW_HOURS` | `24` | Pace window for new profiles |
| `SKILLS_DIR` | `apps/backend/skills` | Skill markdown location |

## Frontend environment (`apps/frontend/.env.local`)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk frontend key |
| `CLERK_SECRET_KEY` | Clerk server key for `auth()` in server components |
| `NEXT_PUBLIC_API_URL` | Backend URL from the browser (`http://localhost:8000`) |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | `/sign-in`, the in-app sign-in route |
| `API_URL` | Backend URL from server components; Compose sets `http://backend:8000` |

## Migrations

The backend container runs `uv run alembic upgrade head` before serving. Outside Compose, run it from `apps/backend`. New migrations go in `apps/backend/alembic/versions/`.

## CI

[`.github/workflows/ci.yml`](../../../../.github/workflows/ci.yml) runs on pull requests and pushes to `main`:

| Job | Steps |
|-----|-------|
| `backend-check` | Postgres 16 service; `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`, `uv run pytest --cov=app --cov-fail-under=70` (tests use `TEST_DATABASE_URL`) |
| `frontend-check` | `npm ci`, `npm run lint`, `npm run typecheck` |

### Running backend checks locally

```bash
docker run -d --name lingua-testdb -p 55432:5432 \
  -e POSTGRES_USER=lingua -e POSTGRES_PASSWORD=lingua -e POSTGRES_DB=lingua_test postgres:16-alpine
cd apps/backend
export TEST_DATABASE_URL=postgresql+asyncpg://lingua:lingua@localhost:55432/lingua_test
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest --cov=app
```

The test session drops and recreates the `public` schema of that database and runs `alembic upgrade head`; every test runs in a transaction that is rolled back.
