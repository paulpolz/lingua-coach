# Lingua Coach

## Concept

A product that wraps a personalized AI English-learning agent into a UI for a public audience. Learners specify their own goals (e.g. "find a job in English in 6 months"), and an AI tutor creates a tailored program, generates daily exercises, checks mistakes, tracks progress, and mentors them at every step.

**Origin:** Built from a working setup where a learner uses a Claude agent with custom skills, artifacts, and workflows for daily English practice — with proven daily use and real outcomes.

---

## Why the Core Idea Is Sound

The setup addresses what most learners want but rarely get in one place:

1. **Goal-first, not curriculum-first** — "Job in English in 6 months" is a real outcome; most apps optimize for streaks and levels.
2. **Continuity** — the same tutor remembers mistakes, tone, pace, and what already failed.
3. **Daily loop** — generate → practice → correct → track. That loop is the product, not "AI chat."

This is validated product research: a real user runs it daily with measurable engagement.

---

## How Complicated Is It?

Think in layers:

| Layer | What it is | Difficulty |
|-------|------------|------------|
| **MVP** | Onboarding (goal, level, time), daily session, corrections, simple progress log | **Moderate** — weeks of focused work for 1–2 devs |
| **"Feels personal"** | Memory, mistake taxonomy, adaptive difficulty, spaced repetition | **Hard** — this is where quality lives |
| **"Feels like a tutor"** | Speaking/pronunciation, roleplay (interviews, meetings), structured retry | **Hard** — voice, latency, evaluation |
| **Production product** | Auth, billing, mobile, retention, content safety, cost control | **Very hard** |

### Technical Shape (Roughly)

- UI (web first is fine)
- Orchestration layer (planner, exercise generator, grader, progress tracker — multi-agent or workflow)
- Persistent learner profile (goals, errors, streaks, CEFR-ish estimates)
- LLM API + optional speech (STT/TTS)

### Hidden Complexity

The hard parts are not the UI:

- **Evaluation** — knowing if an answer is wrong *and why*, with useful feedback
- **Curriculum logic** — when to reinforce vs advance
- **Retention** — people churn when sessions feel random or repetitive
- **Unit economics** — daily LLM (+ voice) usage per user adds up fast

For a pet project: ship a narrow MVP around **one persona** (e.g. "B1→B2, job interview in 6 months, 20 min/day").

---

## What Would Make This Version Defensible

Even as a pet project:

1. **Domain playbook, not generic prompts** — skills for assessment, lesson types, error patterns, "what to do after 3 grammar mistakes on articles," etc.
2. **Outcome templates** — "remote job interview," "relocation," "daily small talk at work" with milestones and mock scenarios.
3. **Visible progress** — learners need to *feel* they're getting somewhere (error heatmap, speaking confidence, interview readiness score).
4. **Opinionated daily ritual** — 15–25 minutes, fixed structure; personalization inside the ritual beats open-ended chat.

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

---

## Suggested Path If We Build It

1. **Document the system** — goals, session types, correction rules, progress signals (this is the IP).
2. **Pick one ICP** — e.g. employed adults, B1–B2, job/career English, 6-month horizon.
3. **MVP** — onboarding → 7-day plan → daily session (text first) → mistake log → weekly recap.
4. **Validate with 10–20 strangers** before voice, payments, or mobile.

### Open Decisions

- Sketch MVP scope (screens + agent graph)
- Compare "fork existing Claude skills" vs "rebuild orchestration in code" for speed vs control