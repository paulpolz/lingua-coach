# Frontend requirements

Status: **locked** (interview)

## Purpose

Web UI for onboarding onto a course plan, daily plan-driven chat practice, visible progress, and plan adjustments. Talks only to the FastAPI backend (plus Clerk hosted auth). Does not call LLM providers directly.

## Stack

| Item | Choice |
|------|--------|
| Framework | **Next.js (App Router) + React** |
| Styling | **Tailwind CSS + shadcn/ui** |
| Auth UI | **Clerk** — email / magic link only; **no Google** in MVP |
| API access | REST + SSE for chat (no WebSocket) |
| Layout | **Mobile-first** responsive |
| Hosting target | See [hosting.md](./hosting.md) |

**Boundary:** UI + Clerk publishable keys + HTTP to FastAPI only. No Gemini keys, no direct Postgres access in the browser.

## Interaction model (B′ — chat-first, plan-driven)

1. **Onboarding** creates the **course plan** (goal, level, topics, vocab priorities, time horizon).
2. **Daily loop** is **chat**: user practices with the tutor; backend injects the plan + **today’s focus**.
3. **Today’s focus** is a thin brief (card on dashboard/chat) — not a full multi-panel exercise worksheet. Generated via the existing lesson job (`POST /lessons/today`, 1 per UTC day) as structured JSON that seeds chat.
4. **Dashboard** shows plan progression and progress (milestones, what’s next, mistake summary).
5. **Settings / plan editor** lets the user **adjust anytime**: goals, topics, vocab priorities → profile / learning goals update → subsequent chats adapt.

```
Onboarding → Course plan → Today’s focus JSON → Daily chat
                ↑                ↓
         Plan editor ←── Profile / progress
```

## MVP pages / routes

| Page | Responsibility |
|------|----------------|
| Onboarding | Capture goal, level, topics/vocab priorities, time budget → create plan via API |
| Dashboard | Plan overview, progress summary, today’s focus card, CTA into chat or “come back tomorrow” if daily focus already consumed |
| Chat | Primary daily practice; SSE tutor replies; today’s focus + plan as context |
| Settings | Clerk account basics + **edit course plan** (goals, topics, vocab, priorities) |

**Not in MVP as separate pages:** dedicated vocabulary page, dedicated progress page (folded into dashboard), marketing site, billing/paywall screens.

## Auth UX

1. Sign in with Clerk magic link
2. Obtain Clerk session token
3. All API calls send `Authorization: Bearer <token>`
4. On first authenticated load, sync user to Postgres (`/auth/sync` or equivalent)
5. No Google OAuth entry point

## API integration

### REST

- Profile / learning goals load and update (including plan editor saves)
- `POST /lessons/today` → `202` + `job_id`, or clear error if daily UTC limit hit
- Poll `GET /jobs/{id}` until terminal; then load today’s focus JSON
- Progress / mistakes summary for dashboard
- Chat session create/list as needed

### SSE chat

- `POST` message with streaming response (`Accept: text/event-stream` or fetch stream)
- Append `token` events; finalize on `done`; surface `error`
- No WebSocket client

## Product rules in UI

- Single product version — **no free/premium badges or paywalls**
- When daily focus is exhausted: empty state (“Come back tomorrow”) — **no upsell**
- Show generation progress while today’s focus job is `pending`/`running`
- Prefer rendering a short focus card + chat over dumping raw markdown worksheets

## UX baseline

- Mobile-first responsive layout
- Loading and error states for jobs, chat, profile, plan save
- Do not block the whole app shell on focus generation — poll in place
- Desktop: same flows; optional denser dashboard layout later (not required for MVP)

## Out of scope (MVP)

- Native mobile apps
- Voice capture / playback
- Offline mode
- Admin UI
- Billing / plan comparison screens
- Full structured exercise worksheets (warmup/dialogue/exercise panels as primary UI)
- Side-by-side lesson+chat desktop layout as a requirement

## Env / config

- `NEXT_PUBLIC_CLERK_*` (publishable)
- Backend API base URL
- No LLM API keys in the frontend

## Dependencies

- Contracts from [backend.md](./backend.md) and [ai-api.md](./ai-api.md) (today’s focus / lesson JSON + chat SSE)
- Plan/progress fields from [database.md](./database.md)
- Auth/hosting alignment with [deployment.md](./deployment.md) and [hosting.md](./hosting.md)
