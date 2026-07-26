# Hosting requirements

Status: **locked** (interview)

## Purpose

Where each component runs in production and what that imposes. Prefer low-ops managed services; free/cheap to **start testing**, with a clear path to a small always-on paid API.

## MVP topology

| Component | Host | Notes |
|-----------|------|-------|
| Frontend (Next.js) | **Vercel** | Hobby free for personal/MVP; Clerk-friendly |
| Backend (FastAPI) | **Railway** | **Single always-on** service; SSE + in-process jobs |
| PostgreSQL | **Railway Postgres** | Same Railway project as the API |
| Auth | **Clerk Cloud** | Magic link; no Google in MVP |
| LLM | **Gemini** | API keys on Railway only — never on Vercel |
| Domain / DNS | **Cloudflare** | Registrar and/or DNS; point apex/www to Vercel, API subdomain to Railway |
| TLS | Vercel + Railway (+ Cloudflare optional proxy) | HTTPS required on all public URLs |

**Rejected for MVP:** Heroku (no meaningful free tier; sleeping Eco dynos unsuitable for SSE/jobs).

## Domain (Cloudflare)

- Use **Cloudflare** for the custom domain: DNS (and optionally registration).
- Typical records:
  - **App (frontend):** apex and/or `www` → Vercel (Cloudflare DNS; follow Vercel’s domain docs)
  - **API:** e.g. `api.<domain>` → Railway (CNAME/target per Railway custom domain)
- When Cloudflare proxy (orange cloud) is enabled in front of Vercel/Railway, verify **SSE / long requests** still work (disable aggressive buffering; prefer DNS-only grey cloud for the API subdomain if streams break).
- After domain is live, update:
  - Clerk allowed origins / redirect URLs
  - Railway `CORS_ORIGINS` / frontend URL
  - Vercel project domain settings
- Local and early prod can keep `*.vercel.app` / Railway default hostnames until the domain is attached.

## Cost posture

| Phase | Expectation |
|-------|-------------|
| **Test / trial** | Vercel ~$0 + Railway trial (~$5 one-time credit) ≈ free to start |
| **Ongoing MVP** | Railway **Hobby ~$5/mo** (+ usage over included credit); Vercel Hobby ~$0 unless limits hit |
| **Not assumed** | Fully free always-on API + Postgres forever |

Do **not** rely on sleeping free dynos for chat/SSE. Prefer a small always-on Railway service.

## Hard constraints

1. **SSE / streaming:** proxy must not buffer the full chat response; timeouts ≥ expected chat duration (e.g. 60–120s+)
2. **Single API instance:** in-process today’s-focus jobs are unsafe across many replicas — one Railway service until a real queue exists
3. **No serverless-only API:** cold starts and sleep break jobs + streaming UX
4. **Secrets:** Vercel env (Clerk publishable + API URL); Railway env (DB, Clerk secret, Gemini keys); never commit secrets
5. **CORS / Clerk:** prod frontend origin (including Cloudflare custom domain) allowlisted on API and in Clerk dashboard

## What not to host (MVP)

| Item | Why |
|------|-----|
| Heroku | Paid-from-day-one; Eco sleep conflicts with architecture |
| Self-hosted LLM GPUs | Out of product scope |
| Self-hosted auth instead of Clerk | Extra ops |
| Redis | Not required until durable jobs |
| Multi-region active-active | Premature |

Docker remains relevant for **local** Postgres (Compose) and optionally as Railway’s deploy packaging — it is not a substitute hosting vendor by itself.

## Environments mapping

| Env | Hosting |
|-----|---------|
| `local` | Laptop + Docker Compose Postgres; Clerk dev; Gemini key |
| `prod` | Vercel (frontend) + Railway (API + Postgres) + Clerk prod + Cloudflare DNS/domain |

## Operational ownership

- **Backups:** enable Railway/managed Postgres backups when available on the plan
- **Migrations:** explicit Alembic step on release (see [deployment.md](./deployment.md))
- **Monitoring:** platform metrics + `GET /health`; Sentry not required for first ship
- **Deploys:** manual (per deployment requirements)

## Dependencies

- Process model from [deployment.md](./deployment.md)
- Service behavior from [backend.md](./backend.md) and [frontend.md](./frontend.md)
