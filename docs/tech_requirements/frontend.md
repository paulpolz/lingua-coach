# Frontend requirements

Status: **locked** (interview)

## Purpose

Chat-first web UI for all **MVP agent skill** use cases: onboarding interview, plan composition and acceptance, lesson coaching, and pace tracking. Talks only to the FastAPI backend (plus Clerk hosted auth). Does not call LLM providers directly.

**Agent skills** ([skills/](../../skills/README.md)) define product behavior; this doc defines the UI surfaces that support them. Post-MVP skill `feedback_giver` (progress dashboard, weekly gates) is out of scope — see [Out of scope](#out-of-scope-mvp).

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

## Skill → UI mapping (MVP)

| Skill | UI surface | User actions | Data from API |
|-------|------------|--------------|---------------|
| `onboarding_interviewer` | Onboarding chat | Answer interview clusters; review summary | SSE chat; profile persisted on interview complete |
| `course_composer` | Same onboarding chat | Refine roadmap in chat; **Accept plan** | Roadmap draft in chat; `POST /onboarding/accept` persists `learning_plans` |
| `exercise_tutor` | Dashboard + lesson chat | Start / resume / stop / finish lesson; practice in chat | Lesson job poll; `lessons.payload`; SSE tutor; mistakes via backend side effects |
| `vocabulary_practice_formats` | Lesson chat (embedded) | Partner/solo vocab drills when tutor selects Format A/B | No separate route — tutor delivers in chat |

**Post-MVP (`feedback_giver`):** dedicated progress / analysis page, weekly assessment session type, structured progress update cards — not built in MVP. MVP shows **pace hints only** on dashboard (plan days done, on pace / behind, projection).

## Interaction model (chat-first, plan-driven)

1. **Onboarding** is a **chat interview** that creates the **course plan** (goal, level, topics, vocab priorities, time budget, **schedule** / target plan days).
2. **Plan refinement and acceptance** happen in the **same onboarding chat**; user must accept before entering the main flow.
3. **Lesson loop** is **chat**: user starts a lesson on demand → backend generates sequential lesson JSON → tutor guides practice using plan + lesson focus + prior progress.
4. **Lesson focus** is a thin brief (card on dashboard/chat) — not a full multi-panel exercise worksheet. Exercise content from lesson JSON is delivered **in chat**.
5. **Plan changes** happen **only in chat** (onboarding or lesson practice). No dedicated plan editor UI.
6. **Dashboard** shows plan summary, **schedule / pace** (plan days done vs target, on pace / behind, projected completion), lesson number / status, and CTA to start, resume, stop, or finish.

```
Clerk sign-in → Onboarding chat → Accept plan → Dashboard
                      ↑                              ↓
              Plan updates ←── Lesson chat ←── Start / resume lesson
```

## MVP pages / routes

| Page | Responsibility |
|------|----------------|
| Sign-in | **MVP entry** — Clerk sign-in / sign-up only (no marketing landing page) |
| Onboarding chat | Chat interview → proposed plan → refine in chat → accept plan |
| Dashboard | Plan overview, **pace / schedule hints**, active lesson status, **Start lesson** / **Resume** / **Finish lesson** |
| Lesson chat | Primary practice; SSE tutor replies; lesson focus + plan as context |
| Settings | Clerk account basics only (sign out, email) — **no plan editor** |

**Not in MVP:** marketing landing page, dedicated analysis/profile/progress page, vocabulary page, billing/paywall screens, plan editor forms.

## Auth UX

1. Unauthenticated users see **Clerk sign-in** as the first screen
2. Obtain Clerk session token after sign-in
3. All API calls send `Authorization: Bearer <token>`
4. On first authenticated load, sync user to Postgres (`/auth/sync` or equivalent)
5. Route guard: if onboarding incomplete → onboarding chat; else → dashboard
6. No Google OAuth entry point

## API integration

### REST

- Profile / learning goals **read** for dashboard display (includes `target_plan_days`, `projected_completion_at`, pace summary; updates come from chat backend side effects)
- `POST /lessons/start` → `202` + `job_id`, or `409` if a generating/active lesson already exists
- Poll `GET /jobs/{id}` until terminal; then load lesson JSON
- `POST /lessons/{id}/finish` — user marks lesson accomplished
- `POST /lessons/{id}/stop` — pause active lesson (optional explicit endpoint; may also be UI-only session leave)
- `GET /lessons/active` — resume flow
- Progress / pace summary for dashboard: plan days completed, target plan days, on pace / behind, projected completion, optional active-lesson time remaining in 24h window
- Chat session create/list; onboarding vs lesson session types

### SSE chat

- `POST` message with streaming response (`Accept: text/event-stream` or fetch stream)
- Append `token` events; finalize on `done` (may include plan-update metadata); surface `error`
- No WebSocket client

## Lesson lifecycle in UI

| State | Dashboard CTA | Chat |
|-------|---------------|------|
| No in-flight lesson | **Start lesson** (shows generation progress while job runs) | Opens new lesson chat after generation |
| Generating / active lesson | **Resume** + **Stop session** + **Finish lesson** | Continue tutor conversation |
| Accomplished (last) | **Start lesson** (next number) | — |

- **Pace hint (active lesson):** optional countdown or “on pace / behind” based on `started_at` + 24h window (from API)
- **Stop session:** leave chat; lesson remains active; dashboard shows Resume; pace clock keeps running
- **Finish lesson:** confirm action → lesson accomplished → unlock Start for next lesson
- Show generation progress while lesson job is `pending` / `running`
- Prefer a short focus card + chat over dumping raw markdown worksheets

## Product rules in UI

- Single product version — **no free/premium badges or paywalls**
- **Plan pacing, not calendar:** one **plan day** = one accomplished lesson; on pace = finish within **24h of lesson start**. User starts the next lesson when ready (one in-flight lesson at a time). Falling behind **reschedules the projection** — does **not** block practice.
- Do not block the whole app shell on lesson generation — poll in place

## UX baseline

- Mobile-first responsive layout
- Loading and error states for jobs, chat, profile load
- Desktop: same flows; optional denser dashboard layout later (not required for MVP)

## Out of scope (MVP)

- Marketing landing page (Clerk sign-in is entry)
- **`feedback_giver` UI** — progress dashboard rows, weekly assessment gates, structured progress-update template ([feedback_giver.md](../../skills/feedback_giver.md))
- Analysis / profile statistics journey (see [cjm.md](../functional_requirements/cjm.md))
- Dedicated plan editor (settings or profile)
- Native mobile apps
- Voice capture / playback
- Offline mode
- Admin UI
- Billing / plan comparison screens
- Full structured exercise worksheets (warmup/dialogue/exercise panels as primary UI)

## Env / config

- `NEXT_PUBLIC_CLERK_*` (publishable)
- Backend API base URL
- No LLM API keys in the frontend

## Dependencies

- Agent skills: [skills/README.md](../../skills/README.md)
- Contracts from [backend.md](./backend.md) and [ai-api.md](./ai-api.md) (lesson JSON + chat SSE + plan updates)
- Plan/progress fields from [database.md](./database.md)
- Journeys from [cjm.md](../functional_requirements/cjm.md)
- Auth/hosting alignment with [deployment.md](./deployment.md) and [hosting.md](./hosting.md)
