# Lingua Coach

## Concept

A product that wraps a personalized AI English-learning agent into a UI for a public audience. Learners specify their own goals (e.g. "find a job in English in 6 months"), and an AI tutor creates a tailored program, generates daily exercises, checks mistakes, tracks progress, and mentors them at every step.

**Origin:** Built from a working setup where a learner uses a Claude agent with custom skills, artifacts, and workflows for daily English practice — with proven daily use and real outcomes.

**Differentiation:** An AI tutor that *knows you* — goal → program → daily mentor — not open-ended chat practice.

---

## Why the Core Idea Is Sound

The setup addresses what most learners want but rarely get in one place:

1. **Goal-first, not curriculum-first** — "Job in English in 6 months" is a real outcome; most apps optimize for streaks and levels.
2. **Continuity** — the same tutor remembers mistakes, tone, pace, and what already failed.
3. **Daily loop** — generate → practice → correct → track. That loop is the product, not "AI chat."

This is validated product research: a real user runs it daily with measurable engagement.

The hard part is not AI — it's encoding a real teaching methodology into a product and maintaining learner state.

---

## Tech requirements (MVP)

Interview-locked stack and contracts live in [`docs/tech_requirements/`](./docs/tech_requirements/README.md):

| Area | Doc |
|------|-----|
| **Agent skills** (pedagogy IP, source of truth) | [skills/](./skills/README.md) |
| Customer journeys (onboarding, student, pacing) | [cjm.md](./docs/functional_requirements/cjm.md) |
| Local MVP gate (setup, contracts, smoke tests) | [implementation-readiness.md](./docs/implementation-readiness.md) |
| Backend (FastAPI, Clerk, REST+SSE, sequential lessons) | [backend.md](./docs/tech_requirements/backend.md) |
| AI API (Gemini-only, collapsed 2-call engine) | [ai-api.md](./docs/tech_requirements/ai-api.md) |
| Database (Postgres, SQLAlchemy+Alembic) | [database.md](./docs/tech_requirements/database.md) |
| Frontend (Next.js, chat-first plan-driven UI) | [frontend.md](./docs/tech_requirements/frontend.md) |
| Deployment (local+prod, manual, Alembic) | [deployment.md](./docs/tech_requirements/deployment.md) |
| Hosting (Vercel + Railway + Cloudflare) | [hosting.md](./docs/tech_requirements/hosting.md) |

```
Frontend (Next.js) → FastAPI → Learning engine (skills) → Gemini → PostgreSQL
```

---

## Agent skills (the product)

Behavior is defined in [`skills/`](./skills/README.md) at repo root — separate from tech requirements, which define how skill outputs persist and render. The agent:

1. **Onboards** the learner (`onboarding_interviewer`) → profile in Postgres
2. **Plans** the program (`course_composer`) → accepted roadmap in Postgres
3. **Conducts** daily lessons (`exercise_tutor`) → lesson artifacts + mistakes in Postgres
4. **Tracks** pace and session outcomes in MVP; full progress feedback loop post-MVP (`feedback_giver`)

All structured outputs are persisted — not inferred from chat history alone. See [database.md](./docs/tech_requirements/database.md).

**MVP skills:** onboarding, course composer, exercise tutor, vocabulary formats. **`feedback_giver` is post-MVP** (progress dashboard, weekly gates, automated replans).

---

## Learning Engine (implementation)

Avoid one giant prompt. MVP collapses to two call types (lesson JSON + chat/correction), each backed by **skill modules** in `skills/`:

```
onboarding_interviewer → course_composer → exercise_tutor
     (profile)              (roadmap)         (lessons + mistakes)
```

Post-MVP adds `feedback_giver` for progress dashboard and plan adjustments. A fuller internal pipeline can still grow behind the same skill boundaries:

```
Goal Analyzer → Curriculum Planner → Lesson Generator → Exercise Generator
    → Correction Engine → Progress Analyzer → Report Generator
```

### Structured outputs

Lessons return JSON the UI can render consistently (see [ai-api.md](./docs/tech_requirements/ai-api.md)):

```json
{
  "lesson_goal": "...",
  "grammar_focus": "...",
  "warmup": [],
  "dialogue": [],
  "exercise": [],
  "review": []
}
```

### Pedagogy engine (the IP)

The valuable part is not the frontend — it is the teaching methodology encoded as **agent skills** ([skills/](./skills/README.md)):

- Skills and workflows (`onboarding_interviewer`, `course_composer`, `exercise_tutor`, …)
- Rubrics and evaluation rules
- Curriculum templates
- Feedback style
- Motivation rules

Prefer **configuration over hard-coding**: onboarding flow, coaching style, lesson templates, assessment rubrics, review cadence, feedback rules, progression logic. Today that config is "Personal English Coach"; later it could be IELTS, Business English, or another language without rewriting the platform.

### Learner memory (not chat history)

Don't ask the model to infer everything from conversations. Store structured knowledge about the learner and inject it into every prompt:

| Profile field | Example |
|---------------|---------|
| Target / goal | Job interview in 18 days |
| English level | B1 → B2 |
| Grammar mastery | Articles: 40, Present Perfect: 82 |
| Vocabulary | Size + consistently missed items |
| Skills | Interview readiness, speaking vs reading confidence |
| Habits | Preferred lesson length, skip patterns, motivation |
| Style | Learning style, review schedule |

Every lesson updates this profile. **Real complexity is state, not prompts.** Schema details: [database.md](./docs/tech_requirements/database.md).

---

## How Complicated Is It?

Think in layers:

| Layer | What it is | Difficulty |
|-------|------------|------------|
| **MVP** | Onboarding (goal, level, time), daily session, corrections, simple progress log | **Moderate** — weeks of focused work for 1–2 devs |
| **"Feels personal"** | Memory, mistake taxonomy, adaptive difficulty, spaced repetition | **Hard** — this is where quality lives |
| **"Feels like a tutor"** | Speaking/pronunciation, roleplay (interviews, meetings), structured retry | **Hard** — voice, latency, evaluation |
| **Production product** | Auth, billing, mobile, retention, content safety, cost control | **Very hard** |

### Hidden Complexity

The hard parts are not the UI:

- **Evaluation** — knowing if an answer is wrong *and why*, with useful feedback
- **Curriculum logic** — when to reinforce vs advance
- **Retention** — people churn when sessions feel random or repetitive
- **Unit economics** — daily LLM (+ voice) usage per user adds up fast
- **State** — each lesson must adapt from level, weak grammar, missed vocab, pace/slips, role target, and confidence gaps

For a pet project: ship a narrow MVP around **one persona** (e.g. "B1→B2, job interview in 6 months, 20 min/day").

No custom model training, GPUs, or inference servers required — the product is orchestration over public LLM APIs.

---

## Monetization & Cost Control

MVP ships as a **single product version** — no billing or free/premium split. Lessons are **sequential and on-demand** (one in-flight at a time); **plan pacing** uses a 24-hour window per plan day (slip reschedules projection, does not block practice). Longer-term freemium thinking still applies:

### Freemium direction (limit experiences, not tokens)

Users don't understand tokens. Limit what they can *do*:

| Free | Pro |
|------|-----|
| One lesson / day | Unlimited lessons & conversations |
| 15-minute session | Voice mode |
| Limited voice | Interview simulation |
| 30-day history | Resume review |
| One active goal | Personal roadmap, weekly reports, priority models |

### Internal cost controls

Budget by tokens internally even if users never see them:

- Short interactions → fast, cheaper model
- Curriculum planning (infrequent) → stronger model
- Weekly reports → higher-end model, once a week
- Reuse generated content where appropriate
- Keep learner profiles compact; avoid shipping full chat history every turn

---

## What Would Make This Version Defensible

Even as a pet project:

1. **Domain playbook, not generic prompts** — skills for assessment, lesson types, error patterns, "what to do after 3 grammar mistakes on articles," etc.
2. **Outcome templates** — "remote job interview," "relocation," "daily small talk at work" with milestones and mock scenarios.
3. **Visible progress** — learners need to *feel* they're getting somewhere (error heatmap, speaking confidence, interview readiness score).
4. **Opinionated daily ritual** — 15–25 minutes, fixed structure; personalization inside the ritual beats open-ended chat.
5. **Configurable methodology** — engine executes teaching config; English coach is the first app, not the whole company.

---

## Competitor Summary

Many adjacent players, few exact matches. "Fully personal AI mentor with a custom program from your life goal" is still a **positioning gap**, not a blue ocean.

### Direct-ish (AI English Tutor)

| Player | Focus |
|--------|--------|
| **Speak, Loora, Langua** | Conversation volume, open-ended practice |
| **ELSA Speak** | Pronunciation and accent coaching |
| **Duolingo Max** | Habit-building + light AI roleplay |
| **Praktika, TalkPal** | Avatar/scenario practice |
| **Eli (Elispeak)** | Scenario loops (interviews, meetings) with repeat-and-improve |
| **Enverson AI** | "Agentic" personalization, mood/memory tracking |

### Indirect

| Player | Focus |
|--------|--------|
| **italki / Cambly** | Human tutors (different model, still "personal") |
| **Babbel, Lingoda** | Structured courses + some live classes |
| **Preply, Pearson, Babbel (enterprise)** | Scale, credentials, B2B workflows |

### Very Close in Spirit (DIY / Open Source)

- [claude-language-tutor](https://github.com/gislio/claude-language-tutor) — multi-agent assessor, sessions, progress tracking; conceptually close to a custom Claude-agent setup
- Various LangGraph-based learning agents — personalized roadmaps, curriculum generation, quiz loops (pet-project / dev-tool level)

### Market Context

- Cloud-based English learning is **large but moderately fragmented** — AI-native apps, human-tutor marketplaces, and assessment platforms coexist.
- Well-funded players (Speak, Preply, Duolingo, etc.) are investing heavily in conversational AI and hybrid human+AI models.
- Differentiation is shifting toward **distribution, workflow integration, and verifiable outcomes** — not just content volume.

### Takeaway

**Many competitors in "AI English practice"; fewer in "AI designs your program from your goal and mentors you daily."** The second is the wedge if workflows are productized, not just wrapped in a chat box.

---

## Honest Verdict

| Question | Take |
|----------|------|
| Good pet project? | **Yes** — real user at home, clear loop, fun to build, portfolio-worthy |
| Good billion-dollar idea as-is? | **Risky** — crowded space, well-funded incumbents, high bar on speaking quality |
| Complicated? | **Moderate MVP, hard to make great** — agent orchestration is tractable; tutor-quality feedback and retention are the grind |
| Many direct competitors? | **Many in AI English; few that nail goal → program → daily mentor end-to-end** |

**Positioning wedge:** Few products nail "your goal → your program → daily mentor" end-to-end. That is the differentiation if the workflows are productized, not just wrapped in a chat box.

**Secret sauce:** The mentor workflow / pedagogy engine — not the React app.

---

## Suggested Path If We Build It

1. **Document the system** — agent skills, session types, correction rules, progress signals (this is the IP). Skills: [`skills/`](./skills/README.md); tech contracts: [`docs/tech_requirements/`](./docs/tech_requirements/README.md); **local MVP gate:** [implementation-readiness.md](./docs/implementation-readiness.md).
2. **Pick one ICP** — e.g. employed adults, B1–B2, job/career English, 6-month horizon.
3. **MVP** — onboarding → course plan → sequential lessons + chat (text first) → mistake log → dashboard pace hints.
4. **Validate with 10–20 strangers** before voice, payments, or mobile.
5. **Keep the repo private first** — prompts, workflows, evaluation, and pedagogy should not go public until intentional.

### Repo layout (local MVP)

```
apps/
  frontend/              # Next.js
  backend/               # FastAPI + Alembic
skills/                  # agent pedagogy IP (source of truth)
prompts/                 # runtime prompt pack (derived from skills)
docker-compose.yml
docs/
```

### Suggested repo layout (broader than the MVP)

English coach is the first application; the platform should outgrow it:

```
apps/
  english-coach/
packages/
  learning-engine/
  memory-system/
  agent-framework/
  evaluation-engine/
```

Optional later hybrid: open-source SDK / UI / demos; keep curriculum engine, user modeling, and evaluation private.
