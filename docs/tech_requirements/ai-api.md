# AI API requirements

Status: **locked** (interview)

## Purpose

Gemini-backed LLM layer used by the backend learning engine. The product is orchestration and pedagogy — not model training. No custom GPUs, self-hosted inference, or multi-provider routing in MVP.

**Pedagogy source of truth:** [skills/](../../skills/README.md) — loaded into system prompts per mode. Do not duplicate skill logic in code; map modes to skill files.

## Principles

1. **Public API only** — Google Gemini (AI Studio / Gemini API); do not train models for MVP
2. **Single provider** — one Gemini client implementation; no multi-provider abstraction in MVP
3. **Structured outputs for lessons** — UI-stable JSON, not free-form markdown as the contract
4. **Two model IDs in config** — faster/cheaper model for chat; stronger model for lesson JSON
5. **Transport independence** — browser SSE/REST does not dictate the provider; backend maps Gemini streams into SSE
6. **Chat-first product** — onboarding, plan refinement, plan adaptation, and practice all use the chat model path
7. **Text-only MVP** — chat input and output are plain text; no STT, TTS, or multimodal audio/video in MVP call paths

## Provider strategy (MVP)

| Role | Choice |
|------|------|
| Provider | **Gemini** only |
| Client | Single Gemini SDK/HTTP client |
| API surface | **`generateContent`** (stream for chat) — not Interactions API / managed agents |
| Chat / onboarding / corrections | Config key e.g. `GEMINI_MODEL_CHAT` (flash-class) |
| Lesson generation | Config key e.g. `GEMINI_MODEL_LESSON` (stronger / pro-class) |
| Fallbacks / other vendors | **Out of MVP** |
| Local models | **Out of MVP** |

Exact model ID strings are environment/config values, not hard-coded in business logic.

Free-tier Gemini usage is acceptable for MVP; rate limits may require a paid key later without changing architecture.

## Orchestration (collapsed)

MVP uses **two call types**, each backed by agent skills:

| Call type | Skills | Model |
|-----------|--------|-------|
| **Generate next lesson** | `exercise_tutor` (+ reads `course_composer` roadmap) | Lesson model |
| **Chat turn** | `onboarding_interviewer` + `course_composer` (onboarding mode) or `exercise_tutor` (+ `vocabulary_practice_formats` when selected) (lesson mode) | Chat model |

1. **Generate next lesson** — one (or repair) completion → structured lesson JSON (`lessons.payload.curriculum`), informed by **prior lessons, progress, and mistakes**
2. **Chat turn** — streamed completion for tutor reply in **onboarding** or **lesson** mode (+ optional structured side metadata on completion)

Keep **skill file boundaries** so steps can be split later without rewriting the product API.

**Post-MVP:** `feedback_giver` as a third call type after lesson accomplish (progress dashboard, weekly gates, replan proposals).

Full README pipeline (Goal Analyzer → … → Report Generator) and Analysis journey outputs are **deferred**.

## Onboarding chat

- Same chat model as lesson practice; prompt/mode distinguishes **onboarding interview**
- Collect: **goal** (why + outcome), level, topics / vocab priorities, **time budget** (cadence + intensity)
- Produce proposed plan in conversation, including **`target_plan_days`** (schedule: estimated plan days ≈ lessons to goal); support refinement turns
- Acceptance is a **product action** (API), not an LLM-only signal — model may detect readiness but backend requires explicit accept and persists schedule fields

## Structured lesson output

Lesson generation must return JSON the frontend can render:

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

Requirements:

- Input context must include learner profile, active plan, and **summaries from the last N accomplished lessons** (default **N = 5**; results, recurring mistakes) — see [database.md](./database.md)
- Validate against a schema (Pydantic) before persisting
- On invalid JSON: **one** repair retry (same or lesson model), then fail the job with a clear error
- Prefer Gemini structured-output / JSON mode when available for the lesson model
- Lesson calls are **non-streaming** (complete JSON, then validate)

## Chat / correction (onboarding + lesson)

- **Modality:** text in, streamed text out — no voice or video payloads in MVP
- Input: learner message (plain text) + compact learner profile + session mode (`onboarding` | `lesson`) + current lesson snippet (lesson mode) + **last N messages** (default **N = 10**)
- Output: streamed tokens for the reply; optional structured side payload on stream end:
  - `corrections`, `tips`
  - **`plan_updates`** — partial profile / goal fields when user feedback implies plan change (may include `target_plan_days`)
  - `suggest_finish` — tutor signals all planned exercises in the lesson curriculum are done (user still taps **Finish lesson** in MVP)
- Persist assistant message after stream completes; backend applies validated `plan_updates`
- Use the chat-configured Gemini model

## Request lifecycle & memory

Gemini is **stateless** — no session memory on Google's side. Each call: FastAPI loads context from Postgres + skills → one Gemini request → persist artifacts back to Postgres ([database.md](./database.md), [backend.md](./backend.md)).

| Tier | Source | Used for |
|------|--------|----------|
| Short-term | Last **N = 10** `chat_messages` (`CHAT_CONTEXT_MESSAGES`) | Conversational continuity |
| Long-term | Profile, roadmap, `lessons.payload` summaries, `mistakes` | Lesson generation + coaching context |

**Prompt assembly:** `system_instruction` ← skill file(s) for the call type (concatenate in orchestration-table order); `contents` ← optional profile/plan block + message history + new user turn.

- Pedagogy lives in **[skills/](../../skills/README.md)** — loaded at runtime (IP); do not log full prompts in production
- **No RAG in MVP** — structured SQL fetch + injection, not vector retrieval over document corpora

## Streaming

- Chat: Gemini stream → backend SSE `token` / `done` / `error` events
- Lesson: non-stream completion → validate → persist (job polling on backend)
- On client disconnect during chat: abandon the provider call when feasible
- Per-request timeouts required (configurable)

## Safety & ops

| Requirement | MVP |
|-------------|-----|
| `GEMINI_API_KEY` (or equivalent) in env / secrets | Required |
| `GEMINI_MODEL_CHAT` / `GEMINI_MODEL_LESSON` | Required |
| Per-request timeout | Required |
| Log provider=`gemini`, model id, latency, token usage when available | Required |
| Content policy / abuse | Basic: reject empty/oversized inputs; deeper moderation later |
| PII in prompts | Minimize; do not log full prompts containing emails/secrets |

## Out of scope (MVP)

- **`feedback_giver`** call type (post-lesson progress analysis, weekly gates)
- RAG / vector retrieval; Gemini managed agents (Interactions API)
- Multi-provider clients or automatic failover
- Full multi-step learning pipeline / weekly report generator
- Analysis journey skill breakdowns and time-to-goal estimation
- Fine-tuning / custom training
- Voice STT/TTS evaluation
- Hugging Face, Groq, OpenRouter, DeepSeek, LLM.kiwi, etc. as wired providers

## Dependencies

- Agent skills: [skills/README.md](../../skills/README.md)
- Consumed by [backend.md](./backend.md) lesson jobs and chat SSE
- Profile fields defined with [database.md](./database.md)
- Lesson JSON contract consumed by [frontend.md](./frontend.md)
- Journeys in [cjm.md](../functional_requirements/cjm.md)
