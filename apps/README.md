# Apps

Local development layout for Lingua Coach.

## Prerequisites

- Docker
- Python 3.11+
- Node.js 20+

## Start Postgres

From repo root:

```bash
docker compose up -d
```

## Backend (FastAPI)

```bash
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # then fill in secrets
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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
