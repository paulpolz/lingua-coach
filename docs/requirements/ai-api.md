# AI API requirements

Status: **locked** (interview)

## Purpose

Gemini-backed LLM layer used by the backend learning engine. The product is orchestration and pedagogy — not model training. No custom GPUs, self-hosted inference, or multi-provider routing in MVP.

## Principles

1. **Public API only** — Google Gemini (AI Studio / Gemini API); do not train models for MVP
2. **Single provider** — one Gemini client implementation; no multi-provider abstraction in MVP
3. **Structured outputs for lessons** — UI-stable JSON, not free-form markdown as the contract
4. **Two model IDs in config** — faster/cheaper model for chat; stronger model for lesson JSON
5. **Transport independence** — browser SSE/REST does not dictate the provider; backend maps Gemini streams into SSE

## Provider strategy (MVP)

| Role | Choice |
|------|--------|
| Provider | **Gemini** only |
| Client | Single Gemini SDK/HTTP client |
| Chat / corrections | Config key e.g. `GEMINI_MODEL_CHAT` (flash-class) |
| Lesson generation | Config key e.g. `GEMINI_MODEL_LESSON` (stronger / pro-class) |
| Fallbacks / other vendors | **Out of MVP** |
| Local models | **Out of MVP** |

Exact model ID strings are environment/config values, not hard-coded in business logic.

Free-tier Gemini usage is acceptable for MVP; rate limits may require a paid key later without changing architecture.

## Orchestration (collapsed)

MVP uses **two call types** only:

1. **Generate today’s lesson** — one (or repair) completion → structured lesson JSON  
2. **Chat / correction turn** — streamed completion for tutor reply (+ optional structured side metadata on completion)

Keep **module/prompt file boundaries** so steps can be split later (planner → generator → checker → progress) without rewriting the product API.

Full README pipeline (Goal Analyzer → … → Report Generator) is **deferred**.

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

- Validate against a schema (Pydantic) before persisting
- On invalid JSON: **one** repair retry (same or lesson model), then fail the job with a clear error
- Prefer Gemini structured-output / JSON mode when available for the lesson model
- Lesson calls are **non-streaming** (complete JSON, then validate)

## Chat / correction

- Input: learner message + compact learner profile + current lesson snippet + **last N messages** (default **N = 10**) — not unbounded full history
- Output: streamed tokens for the reply; optional structured side payload on stream end (corrections, tips)
- Persist assistant message after stream completes
- Use the chat-configured Gemini model

## Context & memory

- Inject a **compact learner profile** (goals, level, grammar scores, weaknesses) into prompts
- Pedagogy content (skills, rubrics, lesson templates, feedback style) lives in **repo config / prompt files** (IP) — not only ad-hoc inline strings
- Do not dump full pedagogy IP into production logs

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

- Multi-provider clients or automatic failover
- Full multi-step learning pipeline / weekly report generator as a hard dependency
- Fine-tuning / custom training
- Voice STT/TTS evaluation
- Hugging Face, Groq, OpenRouter, DeepSeek, LLM.kiwi, etc. as wired providers

## Dependencies

- Consumed by [backend.md](./backend.md) lesson jobs and chat SSE
- Profile fields defined with [database.md](./database.md)
- Lesson JSON contract consumed by [frontend.md](./frontend.md)
