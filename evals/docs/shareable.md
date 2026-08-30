# How we decide the tutor is good

Lingua Coach is a skill-driven tutor (onboarding → roadmap → daily lesson).
Existing tests and Grafana already answer **did the request succeed?** and
**how slow / expensive was it?** They do not answer whether the tutor was
*good*: stayed in the learning language, corrected a real error, and did not
invent curriculum.

This page is the stranger-facing slice of that quality loop. How to run the
harness, add a case, and enable the GitHub check: [`evals/README.md`](../README.md).
Sampling, noise, and what a thin metric must not decide:
[`evals/docs/methodology.md`](methodology.md).

Nothing here is a production transcript. Fixtures are anonymized. There are no
API keys in this tree.

## Four decisions (not one dashboard)

| Decision | What we use | What we do **not** use |
| --- | --- | --- |
| **Ship / don't ship** a skill, prompt, or model change | Offline **regression replay** in CI | Mocked pytest alone; live Gemini; judge scores |
| **Trust a judge dimension** as a future gate | Independent double-label + agreement ~0.7 | Author-proposed labels; a single live κ |
| **Investigate production** | Thumbs and CSAT **1–5** in `quality_events` | `llm_retries_total` (format fragility, not quality) |
| **Grow the suite** | Mine → inbox → human promote → regression | Auto-merging miner stubs into the gate |

Pytest with a mocked Gemini still guards contracts. A skill change can also
fail CI because a **regression case** failed replay — that is the ship gate.

```bash
# Ship gate from repo root. No GEMINI_API_KEY.
PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay
```

CI job `evals-replay` in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
runs that same module invocation after `uv sync` (backend venv +
`PYTHONPATH`; exact Actions snippet: [`evals/CI.md`](../CI.md)). Replay
completions live under `evals/fixtures/replay/`. Capability cases
(`evals/cases/capability/`) are the gold “can still do the job” set; CI
runs **regression replay**, not mocked pytest and not live Gemini. Enable
`evals-replay` as a required check after the first green run on `main`
([`evals/README.md`](../README.md)). Judges never change the process exit
code.

## Metric definitions

Stable enough to compare week to week. Thresholds stay coarse on purpose.

| Question | Metric | Offline | Online | Decision |
| --- | --- | --- | --- | --- |
| Did onboarding finish with a usable plan? | Valid `learner_profile` + `course_roadmap` | Capability cases | Accept / abandon (existing tables) | Skill or interview flow |
| Did the tutor stay in the learning language? | `immersion_pass_rate` — `no_english_learner_facing` on stripped prose; later a judge | Every lesson case | Sample of lesson turns | Block ship if the deterministic check fails on gated cases |
| Was the correction accurate? | Judge `correction_accuracy` vs gold | Capability + regression | Sampled turns with `corrections` | Fix `exercise_tutor` rules |
| Did we invent curriculum? | `groundedness` — `invented_milestone` / `grammar_focus_aligned` | Lesson-generation cases | Failed jobs + judge sample | Tighten generation contract |
| Did the user accept the turn / lesson? | Thumbs up/down; lesson CSAT 1–5 | n/a | All rated `quality_events` | Prioritize mining that cohort |
| Is the judge itself noisy? | `judge_agreement`, `judge_self_consistency` | Calibration set | Periodic re-score | Do not trust the judge yet |
| Are we slower or more expensive? | p95 latency, tokens / turn | Smoke | Prometheus | Model or context-size rollback |

**Gates (initial)**

- **Capability:** all **deterministic** checks must pass.
- **Regression:** **zero** new gated failures vs [`evals/fixtures/baseline.json`](../fixtures/baseline.json). A change that fixes one case and breaks another fails unless the baseline / `expect_fail` set is updated in the same PR.
- **Judges:** informational until independent double-label and agreement
  (κ or % agree) ≥ ~0.7 are written in `methodology.md`. First calibration
  `labels:` are author-proposed. Do not put a noisy dimension on the CI fail
  path; drop it instead.
- **Online:** no page / no ship-no-ship threshold until N ratings is documented.
  Start with “investigate.”

Do not rewrite a skill because thumbs dropped on N < 30. Do not switch models
because one judge run moved 3 points. Full noise rules: `methodology.md`.

## Production signals

Authenticated `POST /api/v1/quality/events` stores:

- **Thumbs** on assistant bubbles after the SSE turn is done (`kind=thumbs`,
  `value.thumb` = `1` or `-1`). UI surfaces: onboarding and lesson.
- **Lesson CSAT** optional **1–5** on Finish (`kind=lesson_csat`). Empty is
  allowed; finish is never blocked. Free-text `learner_feedback` still lands on
  the session summary as before.

Ratings are fire-and-forget. They are **data**, not a second chat log. Chat
rows are deleted on finish; thumbs copy a compact snapshot into the event
while the message still exists so a later batch judge has something to score.

Sampled production judging is **not** on the chat SSE path. Local / nightly:
`python -m evals.judge_online` over `judge_candidate` rows and thumbs-down
snapshots. It writes `kind=judge` (rubric version, scores, model id).

## Grafana — AI Quality

Provisioned dashboard **AI Quality** (`uid: lingua-ai-quality`):

[`infra/monitoring/grafana/provisioning/dashboards/json/ai-quality.json`](../../infra/monitoring/grafana/provisioning/dashboards/json/ai-quality.json)

Local stack: `docker compose --profile monitoring up` (Grafana on port 3001;
see [`infra/monitoring/README.md`](../../infra/monitoring/README.md)).

Default view is the last 7 days. The JSON defines these panels — it does not
commit any rates:

1. Thumbs-down rate by `surface` (onboarding vs lesson)
2. Lesson CSAT (1–5)
3. Judge fail rate by dimension and rubric
4. Existing infra: HTTP p95, `llm_retries_total`, lesson-generation LLM fail

**Those panels will be empty until `quality_events` (and judge fails) exist in
the environment you are looking at.** This write-up does not invent weekly
rates or paste a screenshot of fake traffic. When events exist, use the
dashboard to decide what to mine next — not to page, and not to override the
offline replay gate.

## The loop, once: L1 leakage (not fake prod data)

Success criterion: a tutor failure becomes a checked-in regression case.
This repo has run that loop **once in-repo** on a known failure mode, with
anonymized fixtures — not a fabricated week of production rows.

**Failure.** Spanish-immersion lesson (`native: en`, `target: es`). The learner
may write English (`I go to store yesterday`). A bad tutor turn explains
grammar in English (L1 leakage). `exercise_tutor` already requires
learner-facing text in `target_language`.

**Online (when traffic exists).** `evals.mine` would tag thumbs-down /
“wrong language” feedback as `immersion`, write a stub under
`evals/cases/inbox/` (`suite: inbox`, **not gated**). A human promotes after
stripping PII. Inbox YAML is gitignored until then.

**Promote (already in git).** Same anonymized learner snapshot; gold vs
known-bad pair so CI stays green *and* goes red if someone deletes the
immersion check.

| File | Role |
| --- | --- |
| [`evals/cases/regression/lesson_chat_l1_leakage_es_001.yaml`](../cases/regression/lesson_chat_l1_leakage_es_001.yaml) | Gold: tutor stays in Spanish. `expect_fail: false`. |
| [`evals/cases/regression/lesson_chat_l1_leakage_es_001_caught.yaml`](../cases/regression/lesson_chat_l1_leakage_es_001_caught.yaml) | Known-bad English lecture. `expect_fail: true` — the case **passes** only if `no_english_learner_facing` fails. |
| [`evals/fixtures/learner_a2_travel_es.json`](../fixtures/learner_a2_travel_es.json) | Shared anonymized A2 travel / hotel snapshot (no emails, no real users). |

Deterministic checks: `extract_lesson_turn`, then `no_english_learner_facing`
(policy helper on stripped prose; JSON keys stay English and are ignored).
Replay files under `evals/fixtures/replay/` freeze one completion per id so
CI needs no API key. A skill edit that leaks English on the **gold** case
fails `evals-replay`.

**Capability sibling** (same fixture, gold “still immerses”):
[`evals/cases/capability/lesson_chat_immersion_es_001.yaml`](../cases/capability/lesson_chat_immersion_es_001.yaml).

Hypothetical skill tightening is documented in `methodology.md`; it was
**not** applied in this change. The regression pair already locks the
contract. A real fix would land in the same PR as updated replay fixtures if
the gold string changes.

Weekly ritual after deploy: run `python -m evals.mine`, pick 3–5 stubs or
write “nothing to add,” promote as above. That is how production failures
enter the gate. Details: [`evals/cases/inbox/README.md`](../cases/inbox/README.md).

## What to open next

| Path | Why |
| --- | --- |
| [`evals/README.md`](../README.md) | Commands, case YAML contract, how to update replay |
| [`evals/docs/methodology.md`](methodology.md) | Noise, calibration, what we will not decide |
| [`evals/fixtures/learner_a2_travel_es.json`](../fixtures/learner_a2_travel_es.json) | Sanitized learner / curriculum / roadmap |
| [`evals/cases/regression/lesson_chat_l1_leakage_es_001.yaml`](../cases/regression/lesson_chat_l1_leakage_es_001.yaml) | Gold immersion regression |
| [`evals/cases/regression/lesson_chat_l1_leakage_es_001_caught.yaml`](../cases/regression/lesson_chat_l1_leakage_es_001_caught.yaml) | Known-bad pair (keeps the check honest) |
| [`evals/cases/capability/lesson_chat_immersion_es_001.yaml`](../cases/capability/lesson_chat_immersion_es_001.yaml) | Capability: still in Spanish on a Spanish user turn |
| [`infra/monitoring/grafana/provisioning/dashboards/json/ai-quality.json`](../../infra/monitoring/grafana/provisioning/dashboards/json/ai-quality.json) | AI Quality dashboard definition |
