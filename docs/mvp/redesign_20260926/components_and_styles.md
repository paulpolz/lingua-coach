# Redesign 2026-09-26 — implementation plan

Status: **direction locked**. This file is the plan for the frontend rebuild. Do not change product behavior, API contracts, or routes unless a row in this doc says so.

Locked choices:

- Visual: **warm coach** — stone paper, one teal, Geist. Friendly, not playful.
- Onboarding and lesson **layouts stay**. Paint, type, and chrome change.
- Progress (today’s dashboard) **becomes the Desk home**: next action first, then pace, then a short list. Not a chat page.
- Restyle existing components. Do not add a second widget kit.

References:

- Layout mock: canvas `lingua-product-screens`
- Color/style board: canvas `lingua-style-tokens`
- Tokens: `apps/frontend/app/globals.css` (already defined; use them)
- Product rules: [frontend.md](../init/tech_requirements/frontend.md)
- Skills: [Taste](https://github.com/Leonxlnx/taste-skill), [Emil pick-ui-library](https://github.com/emilkowalski/skills/blob/main/skills/pick-ui-library/SKILL.md), [Impeccable](https://github.com/pbakaus/impeccable)

---

## Requirements

### Must

1. One visual language on onboarding, lesson, and dashboard/home. Token colors only (`background`, `accent`, `tutor-*`, `learner-*`, `muted`, `danger`, `success`, `warning`). No `zinc-*` or `blue-*` on these pages.
2. Chat remains the work: SSE streaming, Enter to send, Shift+Enter newline, markdown coach replies, corrections/tips under the coach bubble.
3. Onboarding stays: start → interview chat → split when a plan draft exists → Accept / Change in chat. No plan editor form.
4. Lesson stays: focus bar, floating checklist, Stop, Finish (always available while active; confirm unfinished slots = 0%).
5. Dashboard/home keeps the lesson lifecycle: idle Start, generating (poll in place), active Resume / Stop / Finish. Pace: plan days done vs target, on pace / behind / ahead, projected completion. Falling behind does not block Start.
6. One filled button per cluster. Finish does not pulse. Send errors stay an inline danger strip with Retry.
7. Mobile-first. Onboarding plan column still stacks above chat under `md`. Checklist still collapses on small screens.
8. Verify in the browser: onboarding start → interview → plan accept; start/resume/finish lesson; dashboard idle, generating, and active.

### Must not

- New routes, marketing page, plan editor, voice, or `feedback_giver` analysis UI.
- New chat/state libraries. No Motion, Sonner, or shadcn install required for this pass.
- Invent calendar data. `GET /progress` has no week history (see Progress page).
- Remove Clerk report items (Error Log, Roadmap, 4-Week Plan, Progress **report** at `/reports/progress`). Home is `/dashboard`. Those reports stay in the account menu.
- Change backend, SSE, lesson jobs, or copy that is product-factual (confirm Finish text, pace window rules).

### Nice if cheap

- `Button` `size="sm"` instead of ad-hoc compact classes.
- Base UI dialog later for Finish confirm (today `window.confirm` is acceptable).
- Phosphor icons only if a glyph is truly needed; text labels are enough.

---

## Scope

| In | Out |
|---|---|
| `AppHeader`, `Button`, bubbles, composer | Sign-in / Clerk hosted screens |
| Onboarding intro, interview, plan column | `/reports/*` visual pass (optional leftover) |
| Lesson focus bar, checklist, finish-ready line | New navigation (tabs, rails, bottom nav) |
| Dashboard → Desk home | Installing shadcn, Motion, Sonner |
| Strip zinc/blue on those surfaces | Backend or copy of skills |

---

## Implementation order

Do shared chrome first so pages inherit it.

1. **`Button`** — compact size; dashboard/lesson stop hand-rolling buttons.
2. **`AppHeader`** — 52px, muted brand, token colors.
3. **`ChatMessageBubble` + `ChatComposer`** — thread 560px, radii, corrections, danger strip, no always-on helper line.
4. **Onboarding** — borderless intro; `PlanSummaryCard` as a list.
5. **Lesson** — focus bar, ghost Stop, Finish primary only when `suggest_finish`, no pulse, borderless checklist, finish-ready line without a second Finish.
6. **Dashboard/home** — Desk layout; all existing phases; no zinc/blue cards.
7. **Sweep** — remaining `zinc-*` / `blue-*` on these files; dark mode via tokens.
8. **Browser check** — flows in Must §8.

---

## Shared system

### Color

One family: stone paper + teal. Do not mix zinc/slate/blue into these screens.

| Token | Light | Dark | Use |
|---|---|---|---|
| `background` | `#faf9f7` | `#0c0a09` | Page |
| `surface` | `#ffffff` | `#1c1917` | Header, composer, plan column |
| `surface-muted` | `#f5f4f1` | `#292524` | Hover, checklist, quiet fills |
| `foreground` | `#1c1917` | `#f5f5f4` | Primary text; learner bubble fill (light) |
| `muted` | `#78716c` | `#a8a29e` | Labels, helper, brand in header |
| `border` | `#e7e5e4` | `#292524` | Hairlines |
| `border-strong` | `#d6d3d1` | `#44403c` | Inputs, secondary buttons |
| `accent` | `#0d9488` | `#2dd4bf` | Primary actions |
| `accent-hover` | `#0f766e` | `#5eead4` | Hover only |
| `tutor` | `#0f766e` | `#2dd4bf` | Coach label |
| `tutor-soft` | `#ccfbf1` | `#134e4a` | Coach bubble fill |
| `tutor-fg` | `#134e4a` | `#ccfbf1` | Coach bubble text |
| `learner` | `#1c1917` | `#f5f5f4` | Learner bubble fill |
| `learner-fg` | `#fafaf9` | `#1c1917` | Learner bubble text |
| `success` | `#059669` | `#34d399` | On pace only |
| `warning` | `#b45309` | `#fbbf24` | Corrections, behind pace |
| `danger` | `#dc2626` | `#f87171` | Send/finish failure |

If a screen has no error and no pace problem, it is paper + teal only.

### Type

Geist Sans everywhere. Geist Mono only for markdown `code`. Sentence case. No uppercase section banners.

| Role | Size / line | Weight | Color |
|---|---|---|---|
| Progress hero / onboarding start title | 22 / 28 | 590 | `foreground` |
| Chat body | 14 / 22 | 400 | `tutor-fg` / `learner-fg` |
| Field value | 14 / 20 | 550 | `foreground` |
| Header page title | 13 / 18 | 600 | `foreground` |
| Brand in header | 13 / 18 | 500 | `muted` |
| Button (default) | 14 / 20 | 600 | on-accent or `foreground` |
| Button (compact) | 12 / 16 | 600 | same |
| Label | 11 / 16 | 400 | `muted` |

Tracking: `-0.03em` on 22px titles, `-0.01em` on 13–14px titles.

### Shape and motion

| Element | Radius | Motion |
|---|---|---|
| Buttons, inputs | 12px | Press `scale(0.97)`, 120ms `cubic-bezier(0.23, 1, 0.32, 1)`. Color 150ms ease. |
| Coach bubble | `4px 16px 16px 16px` | None on send |
| Learner bubble | `16px 4px 16px 16px` | None |
| Banners | 8px | Enter 180ms ease-out. No pulse, no loop. |
| Header / columns | 0 (flush in shell) | None |
| Brand mark | 6px | None |

Structure with 1px `border`, not drop shadows. Keyboard actions stay instant.

### Do not use

- Dashboard blue (`blue-50` / `blue-600`) for the active lesson
- Zinc body copy on dashboard
- Pulsing Finish
- Green nested plan card (success color means “done”; the plan is still a draft)
- Inter, purple, gradients, glass
- Two filled buttons in one cluster
- Uppercase chrome labels (`PROPOSED PLAN`, `LESSON PLAN`)
- Always-on “Enter to send” caption (behavior stays; the line is noise after the first sends)

---

## Shared components

Restyle the existing files. Do not invent parallel widgets.

### `AppHeader`

**File:** `apps/frontend/components/AppHeader.tsx`

**Used on:** onboarding, lesson, progress (home).

| Part | Style |
|---|---|
| Bar | Height 52px · `background` · bottom hairline `border` · padding 0 20px |
| Brand mark | 22×22 · radius 6px · `accent` fill · white “L” |
| Brand name | 13 / 500 · `muted` · recedes |
| Divider | 1×18px `border` |
| Page title | 13 / 600 · `foreground` |
| Description | 11 / `muted` · one line |
| Account | Clerk `UserButton` · no extra chrome |

Copy:

| Page | Title | Description |
|---|---|---|
| Onboarding | Let's get you set up | Goal, level, and a plan you can change. |
| Lesson | Lesson {n} | Lesson goal (e.g. Past simple at the cafe) |
| Home | Home | Next lesson and pace |

### `AccountMenu`

**File:** `apps/frontend/components/AccountMenu.tsx`

No structural change in this pass. Reports stay. Home is `/dashboard`, not a new nav item.

### `Button`

**File:** `apps/frontend/components/ui/Button.tsx`

Every action on these pages goes through this set.

| Variant | Style | When |
|---|---|---|
| Primary | `accent` fill · white (dark: stone-950) · hover `accent-hover` | The one action: Start, Send, Accept, Finish when ready, Resume |
| Secondary | 1px `border-strong` · `surface` · `foreground` | Rare; prefer ghost |
| Ghost | No fill, no border · `muted` · hover `surface-muted` | Change, Stop, Dismiss, Finish when not suggested |
| Danger | `danger` fill | Errors only. Finish stays primary teal. |

| Size | Height | Padding | Type |
|---|---|---|---|
| Default | 40px | 10px 16px | 14 / 600 |
| Compact | 32px | 6px 10px | 12 / 600 · lesson bar only |
| Send | 40px · min-width 72px | same as default | Empty → disabled. Sending → three dots, same height. |

Focus: 2px ring `accent` at 20%. Disabled: opacity 50, no press.

### `ChatMessageBubble`

**File:** `apps/frontend/components/ChatMessageBubble.tsx`

**Used on:** onboarding interview, onboarding plan-ready chat, lesson chat.

| Part | Style |
|---|---|
| Thread | Max width 560px · centered · gap 16px |
| Coach wrap | Align start · max 85% |
| Coach label | 11 / 550 · `tutor` · 4px below, **outside** the fill |
| Coach body | `tutor-soft` · `tutor-fg` · 14 / 22 · padding 10px 14px · radius `4 16 16 16` |
| Learner | Align end · max 78% · `learner` · `learner-fg` · same type/padding · radius `16 4 16 16` |
| Streaming | Three 4px dots in `tutor` · no spinner card |
| Markdown | Existing `chat-markdown` rules · list markers `tutor` |

#### Corrections (inside coach bubble)

No “CORRECTIONS” / “TIP” headings.

| Part | Style |
|---|---|
| Divider | 1px `border` · 12px above, 10px padding-top |
| Pair | 13 / 20 · strikethrough `muted` · `→` · correction 600 `foreground` |
| Tip | 12 / italic · `muted` · under the pairs |

### `ChatComposer`

**File:** `apps/frontend/components/ChatComposer.tsx`

**Used on:** onboarding interview, onboarding plan-ready, lesson.

| Part | Style |
|---|---|
| Bar | `background` (same as page) · top hairline `border` · padding 12px 20px 14px |
| Inner | Max width **560px** · centered · textarea + Send (same column as bubbles) |
| Textarea | Min 44px · max 180px · radius 12px · `border-strong` · 14 / 22 · focus border `accent` + 2px ring 20% |
| Send | Primary 40px |
| Helper | Remove the always-on “Enter to send · Shift+Enter…” line. Keep the keybindings. |
| Error | `danger-soft` strip above the field · 13px `danger` · ghost Retry |

Hidden on onboarding start (before first message), same as today.

---

## Page: Onboarding

**Route:** `/onboarding`  
**Files:** `app/onboarding/page.tsx`, `OnboardingChat.tsx`, `PlanSummaryCard.tsx`  
**Layout:** unchanged. Full-width chat until a plan exists; then left plan column + right chat.

Shell: `h-dvh` column · `AppHeader` as in the copy table.

### Start (empty interview)

| Component | Notes / styles |
|---|---|
| `AppHeader` | Shared |
| Intro block | Centered · max 400px · **no bordered card** |
| Title | 22 / 28 / 590 · “Let's build your learning plan” |
| Body | 14 / 22 · `muted` · max 34ch |
| `Button` primary | “Start” · 40px · only filled control |

### Interview (chat, no plan yet)

| Component | Notes / styles |
|---|---|
| `AppHeader` | Shared |
| Thread | Padding 28px 20px 20px · `ChatMessageBubble` |
| `ChatComposer` | Shared |

### Plan ready (split)

| Component | Notes / styles |
|---|---|
| `AppHeader` | Shared |
| Plan column | Width 36% (min 280, max 400) · right hairline · padding 20px 20px 24px |
| `PlanSummaryCard` | Plain column, not a green card |
| Chat column | Same thread + composer as interview |

#### `PlanSummaryCard` (onboarding only)

**File:** `apps/frontend/app/onboarding/PlanSummaryCard.tsx`

Green + check mark reads as accepted; this is still a draft. Nested milestone cards are noise. Keep Accept and Change.

| Part | Style |
|---|---|
| Title | 13 / 600 “Proposed plan” · inline “Updated” 11 `muted` · no check badge, no uppercase |
| Goal | Full width · label 11 `muted` · value 14 / 550 |
| Meta grid | 2 columns · Horizon, Level, Length, Range |
| Pace line | 13 / 20 `muted` |
| Milestones | Sentence-case titles · days 12 `muted` · detail 12 / 18 `muted` · hairline between rows · no nested cards |
| Weekly session | Label 12 `muted` · activities as text (“Warm-up 4m”), not pills |
| Actions | Primary **Accept** + ghost **Change** · pinned to column bottom |
| Regenerating | Overlay copy “Updating your plan…” · no extra card |
| Accept error | `danger-soft` · `danger` text |

One filled button: Accept.

---

## Page: Lesson (learning)

**Route:** `/lesson/[lessonId]`  
**Files:** `app/lesson/[lessonId]/page.tsx`, `LessonChat.tsx`, `LessonChecklist.tsx`  
**Layout:** unchanged. Header → focus bar → thread with floating checklist → composer.

### `LessonTopBar` (in `LessonChat.tsx`)

| Part | Style |
|---|---|
| Bar | Padding 8px 20px · bottom hairline · `background` |
| Title control | 13 / 550 · toggles focus |
| Focus detail | 12 `muted` · one line: “Grammar: … · Vocab: …” |
| Stop session | Ghost compact (32px) |
| Finish lesson | Primary compact when `suggest_finish` · ghost compact otherwise |
| Finish error | `danger-soft` strip under the bar · Retry + Dismiss as ghost text |

Keep the Finish confirm (`unfinished slots count as 0%`). Do **not** pulse Finish. Do **not** put a second Finish on the notice.

### Finish-ready notice

| Part | Style |
|---|---|
| Placement | Above composer · inside the 560px thread width |
| Type | 12 `muted` · “Drill is the last task. Finish from the bar when you are ready.” |
| Button | None (action lives on the bar) |
| Motion | 180ms ease-out enter |

### `LessonChecklist`

**File:** `apps/frontend/app/lesson/[lessonId]/LessonChecklist.tsx`

| Part | Style |
|---|---|
| Position | Absolute top-right of the thread (same as today) · width 168px · no card border |
| Header | 11 `muted` “Lesson plan” · count “2/3” |
| Rows | 12 / 20 · current task `foreground` · done `muted` + strikethrough · minutes `muted` |
| Mobile | Collapse to header; expand on tap (keep current behavior) |

Thread gets `margin-right: 176px` on desktop so bubbles do not sit under the list. Bubble column stays 560px.

### Lesson thread + composer

Same `ChatMessageBubble` and `ChatComposer` as onboarding. Empty lesson: one centered line 14 `muted`, no card.

Error/loading on this page: one line + ghost Retry (no zinc spinner card).

---

## Page: Progress (home)

**Route:** `/dashboard`  
**Files:** `app/dashboard/page.tsx`, `DashboardClient.tsx`, `PaceSummary.tsx`  
**Layout change:** replace the centered card stack with the Desk home. **Data and phases stay.**

Shell: `AppHeader` “Home” / “Next lesson and pace”.

Page column: max 640px · centered · padding 36px 28px 40px · gap 28px · `background`.

### Phases (keep all)

| Phase | UI |
|---|---|
| Loading | One line “Loading…” + ghost Retry if it fails. No spinner card. |
| Idle | Hero “Ready for lesson {n}?” · 14 `muted` focus line · primary **Start lesson** |
| Starting / generating | Same hero slot · elapsed `m:ss` 13 `muted` · timeout: `warning` copy + ghost **Check again** |
| Generation failed | `danger` line + primary **Try again** (the only filled button) |
| Active | Hero “Resume lesson {n}?” · goal/grammar/vocab as 14 `muted` lines (not a blue card) · primary **Resume** · ghost **Stop session** + ghost **Finish lesson** |
| Finish ack | One line 13 `muted` + ghost Dismiss · **no filled banner box** |

### Pace

`PaceSummary` stays the `GET /progress` source. Restyle: no card.

| Part | Style |
|---|---|
| Bar | Labels “Plan days” / “{done} / {target}” · filled segment `success` |
| Meta | 12 `muted` · “On pace · Projected {date} · {level if available}” |
| Behind | Only the “Behind pace” fragment uses `warning` |
| Past 24h window | Existing copy, `warning`, still does not block Start |

Level (`B1`) is not on `Progress` today. Omit it unless it is already on the profile payload you fetch. Do not hardcode.

### “This week” list

The mock used Mon/Wed/Fri. **`GET /progress` has no lesson history.** Do not invent calendar rows.

| If | Then |
|---|---|
| No history endpoint (today) | **Omit** the week list. Pace bar + meta is enough. |
| History exists later | Hairline rows: 14px · day or lesson number 550 · note `muted` |

---

## Component × page matrix

| Component | Onboarding | Lesson | Progress |
|---|---|---|---|
| `AppHeader` | yes | yes | yes |
| `AccountMenu` | yes | yes | yes |
| `Button` | Start / Accept / Change / Send | Stop / Finish / Send | Start or Resume · Stop/Finish if active |
| `ChatMessageBubble` | interview + plan chat | yes | no |
| `ChatComposer` | interview + plan chat | yes | no |
| `PlanSummaryCard` | plan-ready column | no | no |
| `LessonTopBar` | no | yes | no |
| `LessonChecklist` | no | yes | no |
| Finish-ready notice | no | yes | no |
| Finish ack line | no | no | yes |
| Hero + primary CTA | Start block only | no | yes |
| Pace bar | no | no | yes |
| Week list | no | no | only if history exists |

---

## File mapping

| File | Change |
|---|---|
| `components/ui/Button.tsx` | Compact size; keep press motion; all page CTAs use this |
| `components/AppHeader.tsx` | 52px, muted brand, token colors |
| `components/ChatMessageBubble.tsx` | Asymmetric radii, label outside fill, correction/tip restyle |
| `components/ChatComposer.tsx` | 560px inner; remove helper line; keep danger strip + Retry |
| `app/onboarding/PlanSummaryCard.tsx` | List + Accept/Change; no green card / nested tiles |
| `app/onboarding/OnboardingChat.tsx` | Intro without bordered card; keep split |
| `app/onboarding/page.tsx` | Header copy only |
| `app/lesson/[lessonId]/LessonChat.tsx` | Focus bar; Finish primary iff `suggest_finish`; no pulse; finish-ready line |
| `app/lesson/[lessonId]/LessonChecklist.tsx` | Borderless list |
| `app/lesson/[lessonId]/page.tsx` | Token colors on error/back links |
| `app/dashboard/page.tsx` | Header copy “Home” |
| `app/dashboard/DashboardClient.tsx` | Desk home; all phases; `Button` only |
| `app/dashboard/PaceSummary.tsx` | Bar + meta row, no card |
| `app/globals.css` | Tokens stay; no new palette |

---

## Acceptance

- [ ] Onboarding start, interview, and plan-ready split still work (SSE, Accept, Change).
- [ ] Lesson send/stream/retry, checklist, Stop, Finish + confirm still work.
- [ ] Dashboard idle / generating / failed / active still work; poll does not block the shell.
- [ ] No `zinc-*` or `blue-*` on the files in the mapping (reports pages may wait).
- [ ] One filled button per visible cluster; Finish never pulses.
- [ ] Composer inner width matches the bubble column (560px).
- [ ] Dark mode uses the existing `globals.css` dark tokens.
- [ ] Desktop and a mobile width: onboarding stack, checklist collapse, 44px composer target.

Libraries if you need a reference while building (not required installs):

- [shadcn Button](https://ui.shadcn.com/docs/components/button) — pattern, not a new package
- [Phosphor](https://phosphoricons.com) — icons if any
- [CVA](https://cva.style) — optional for `Button` sizes
- [Base UI Dialog](https://base-ui.com/react/components/dialog) — optional Finish confirm later
- [Sonner](https://sonner.emilkowal.ski) — do not use for composer errors
- [easing.dev](https://easing.dev) — press curve
