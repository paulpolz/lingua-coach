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
- App: `http://localhost:3000`

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
