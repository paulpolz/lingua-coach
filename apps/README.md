# Apps

Local development layout for Lingua Coach.

## Prerequisites

- Docker
- Python 3.11+ ([uv](https://docs.astral.sh/uv/)) — only if running backend migrations or backend on the host
- Node.js 20+ — only if running frontend on the host

## First-time setup

From repo root:

```bash
cp apps/backend/.env.example apps/backend/.env          # once; fill in secrets
cp apps/frontend/.env.example apps/frontend/.env.local  # once; fill in secrets
```

## Start everything (Docker Compose)

From repo root:

```bash
docker compose up --build
```

This starts Postgres, the FastAPI backend (port 8000), and the Next.js frontend (port 3000) with hot reload via volume mounts. The backend runs `alembic upgrade head` on startup before serving requests.

Verify:

- Health: `GET http://localhost:8000/api/v1/health`
- Metrics: `GET http://localhost:8000/metrics`
- App: `http://localhost:3000`

### Local monitoring (optional profile)

Prometheus, Loki, Promtail, and Grafana are opt-in via Compose profile:

```bash
docker compose --profile monitoring up --build
```

| Service | URL |
|---------|-----|
| Grafana | http://localhost:3001 (anonymous Viewer, or `admin` / `admin`) |
| Prometheus | http://localhost:9090 |
| Loki | http://localhost:3100 |

Pre-provisioned dashboards: **API Overview**, **LLM & Token Burn**, **Errors & Correlation**. To debug a request, copy `X-Request-ID` from the browser Network tab and filter logs with:

```
{service="backend"} | json | request_id="<uuid>"
```

See [`docs/mvp/monitoring_20260811/monitoring_20260811.md`](../docs/mvp/monitoring_20260811/monitoring_20260811.md) for the prod Railway log runbook.

To run migrations manually (e.g. after pulling new migration files without restarting the stack):

```bash
docker compose exec backend uv run alembic upgrade head
```

## Start Postgres only

If you prefer running backend/frontend on the host:

```bash
docker compose up -d postgres
```

## Backend on host (FastAPI)

```bash
cd apps/backend
uv sync
cp .env.example .env   # then fill in secrets
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend on host (Next.js)

```bash
cd apps/frontend
npm install
cp .env.example .env.local   # then fill in secrets
npm run dev
```
