# Apps

## Prerequisites

- Docker
- Python 3.11+ with [uv](https://docs.astral.sh/uv/), only to run the backend on the host
- Node.js 20+, only to run the frontend on the host

## First-time setup

From the repo root:

```bash
cp apps/backend/.env.example apps/backend/.env          # fill in secrets
cp apps/frontend/.env.example apps/frontend/.env.local  # fill in secrets
```

## Docker Compose

```bash
docker compose up --build
```

This starts Postgres, the FastAPI backend on port 8000, and the Next.js frontend on port 3000, with hot reload through volume mounts. The backend runs `alembic upgrade head` before serving.

Check:

- Health: http://localhost:8000/api/v1/health
- Metrics: http://localhost:8000/metrics
- App: http://localhost:3000

Run migrations by hand after pulling new ones:

```bash
docker compose exec backend uv run alembic upgrade head
```

### Monitoring profile

```bash
docker compose --profile monitoring up --build
```

| Service | URL |
|---------|-----|
| Grafana | http://localhost:3001 (anonymous viewer, or `admin` / `admin`) |
| Prometheus | http://localhost:9090 |
| Loki | http://localhost:3100 |

Dashboards: **API Overview**, **LLM & Token Burn**, **Errors & Correlation**. To trace one request, copy `X-Request-ID` from the browser network tab and query Loki:

```
{service="backend"} | json | request_id="<uuid>"
```

## Backend on the host

```bash
docker compose up -d postgres
cd apps/backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend on the host

```bash
cd apps/frontend
npm install
npm run dev
```

Checks used in CI: `npm run lint` and `npm run typecheck` in `apps/frontend`, and `uv run python -c "import app.main"` plus `uv run python -m unittest tests.test_structured_output` in `apps/backend`.
