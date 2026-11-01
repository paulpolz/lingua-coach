# Frontend

Next.js 16 App Router app for Lingua Coach. See [frontend.md](../../docs/mvp/init/tech_requirements/frontend.md) for routes, screens, and API clients.

## Environment

Copy `.env.example` to `.env.local` and fill in the Clerk keys and `NEXT_PUBLIC_API_URL`.

The sign-in page sends sign-in and sign-up to `/onboarding`. The onboarding page sends completed users to `/dashboard`. [`PostAuthRedirect`](./components/PostAuthRedirect.tsx) on the sign-in page and [`RootAuthGate`](./components/RootAuthGate.tsx) on `/` handle Clerk finishing auth on the client before the server session cookie is ready.

## Commands

```bash
npm install
npm run dev        # http://localhost:3000
npm run lint
npm run typecheck
```
