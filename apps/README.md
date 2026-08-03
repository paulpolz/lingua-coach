# Apps

Local development layout for Lingua Coach.

## Prerequisites

- Docker
- Python 3.11+ ([uv](https://docs.astral.sh/uv/))
- Node.js 20+

## Start Postgres

From repo root:

```bash
docker compose up -d
```

## Backend (FastAPI)

```bash
cd apps/backend
uv sync
cp .env.example .env   # then fill in secrets
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/api/v1/health`

## Frontend (Next.js)

```bash
cd apps/frontend
npm install
cp .env.example .env.local   # then fill in secrets
npm run dev
```

Open `http://localhost:3000`