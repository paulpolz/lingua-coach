# Language Tutor — AI Quality Eval Loop

## 1. Objective

Add a first-class **evaluation loop** around the existing tutor — without changing the teaching architecture.

The agent is only as good as the evals we run on it. Today we can tell whether a request succeeded, how long it took, and whether JSON parsed. We cannot tell whether the tutor was *good*: right language, grounded in the plan, useful correction, no invented curriculum.

This work closes that gap:

- **Offline quality gates** before a prompt, skill, or model change ships.
- **Online quality signals** after launch (user + judge + infra).
- **A closed loop:** mine real failures → regression cases → change the product.

This is the layer [monitoring_20260811.md](../monitoring_20260811/monitoring_20260811.md) §6 deferred ("AI quality monitoring, separate from infrastructure"). It runs on the current stack: skill markdown, SQL-assembled context, Pydantic artifacts, Gemini.

The product goal is not "more dashboards." It is **decisions**: ship / don't ship / rollback / rewrite a skill.

---



## 2. Current state

What already exists and should be reused, not rebuilt.

### Quality-adjacent (keep)

| Piece | Where | Role in the loop |
|-------|--------|------------------|
| Skill modules | `skills/*.md` | Behavior under test |
| Structured side-payloads | `extraction.py`, `skills.py` contracts | Deterministic parse of model output |
| Schema + one repair retry | `lesson_generation.py` | Pre-launch *format* gate |
| Learner mistake taxonomy + SR | `mistakes`, `chat.py` upsert | Product feedback loop (learner errors) |
| Session summary + `learner_feedback` | `lessons.payload`, finish API | Weak online signal, already persisted |
| Plan updates from chat | `PlanUpdates` → `profiles` | Adaptation audit trail |
| Infra metrics | `app/core/metrics.py`, Grafana | Latency, tokens, retries, HTTP errors |
| Unit/integration tests | `apps/backend/tests/` | Mocked Gemini — **contracts**, not quality |

### Repo / CI (decided)

| Piece | Where | Role in the loop |
|-------|--------|------------------|
| Public repository | GitHub `paulpolz/lingua-coach` | Unlimited standard Actions minutes; open visibility |
| Branch protection | GitHub → `main` | Changes via PR; solo merge, no required human approval |
| Offline eval gate | `.github/workflows/ci.yml` (Phase 1) | `evals.run --replay` on every PR + push to `main` (§5.4) |

### Missing

- Gold conversations / capability and regression datasets
- LLM-as-judge (or any scored quality metric)
- Judge methodology (agreement, variance, non-determinism)
- Per-turn thumbs / CSAT as first-class events
- Mining **tutor** failures (wrong language, bad correction, hallucinated plan) as distinct from **learner** mistakes
- A ship/no-ship report a human can read in five minutes

```text
Today                         Target
-----                         ------
request ok?          →        was the tutor good?
JSON valid?          →        artifact correct *and* pedagogically sound
learner mistake log  →        tutor failure log + regression cases
latency / tokens     →        those + resolution / CSAT / judge score
pytest (mocked LLM)  →        pytest + live/replay eval suite
```

---



## 3. Design principle

Separate three layers. Do not mix them in one table or one dashboard.

```text
PostgreSQL
= "What happened for this learner?" (profile, lessons, mistakes)

Infra metrics (Prometheus)
= "Did the system work?" (latency, tokens, 5xx, retries)

Eval loop (this doc)
= "Was the AI good — and should we change it?"
```

```text
SQL context     = what we know about the learner
Skills          = what the agent is supposed to do
Offline suite   = do we still do that on known cases?
Online signals  = is production drifting?
Mining          = which new cases enter the suite this week?
```

**Rules**

1. A metric without a decision is noise. Every metric in §4 names a decision.
2. Offline gates are **blocking** for skill/prompt/model changes once the suite exists. Online dashboards are **informing** until volume is honest.
3. Deterministic checks (schema, language policy, required JSON markers) run *before* an LLM judge. Do not spend tokens judging invalid output.
4. Learner `mistakes` stay the pedagogy store. Tutor failures live in `evals/` (offline) and a small `quality_events` table (online).

---



## 4. Quality questions and metrics

Start from the business question, then the metric. Definitions must be stable enough to compare week to week.

| Question | Metric | Offline | Online | Decision |
|----------|--------|---------|--------|----------|
| Did onboarding finish with a usable plan? | `onboarding_complete_rate` — valid `learner_profile` + `course_roadmap` emitted and accepted | Capability cases | Accept / abandon | Skill or interview flow rewrite |
| Did the tutor stay in the learning language? | `immersion_pass_rate` — judge + deterministic language hints | Every lesson case | Sample of lesson turns | Block ship if below threshold |
| Was the correction accurate? | `correction_accuracy` — judge vs gold span / pattern | Regression + capability | Sampled turns with `corrections` | Fix `exercise_tutor` rules |
| Did we invent curriculum? | `groundedness` — lesson JSON only uses profile / plan / due mistakes | Lesson-generation cases | Failed jobs + judge sample | Tighten generation contract |
| Did the lesson match today's slot? | `plan_alignment` | Lesson-generation cases | Thumbs + finish feedback | Course composer vs tutor |
| Did the user accept the turn / lesson? | `thumbs_up_rate`, `lesson_csat` | n/a | All rated events | Prioritize mining that cohort |
| Is the judge itself noisy? | `judge_agreement` (human vs judge), `judge_self_consistency` (repeat-3) | Calibration set | Periodic re-score | Do not trust the judge yet |
| Are we slower or more expensive? | p95 latency, tokens / turn (existing) | Smoke on suite | Prometheus | Model or context-size rollback |

**Thresholds (initial — calibrate in Phase 2, do not invent precision)**

- Offline capability: all **deterministic** checks must pass; judge scores are informational until agreement ≥ ~0.7 on the calibration set.
- Offline regression: **zero** new failures vs last tagged baseline. A change that fixes one case and breaks another is a failed gate unless explicitly accepted.
- Online: no ship/no-ship threshold until N ratings is documented (start with "investigate," not "page").

**What we will not decide from a noisy metric**

- Do not rewrite a skill because thumbs dropped on N < 30.
- Do not switch models because one judge run moved 3 points.
- Do not treat `llm_retries_total` as quality — it is format fragility.

---



## 5. Offline eval suite

A small, versioned dataset plus a runner. Prefer 30–50 excellent cases over 500 unlabeled ones.

### 5.1 Suite kinds

**Capability** — "the agent can still do the job."

Examples:

- Onboarding: given a short transcript, model emits a valid `learner_profile` with both languages and a `course_roadmap` whose `target_language` matches.
- Lesson chat: tutor reply is in `target_language`; `json:lesson_turn` parses; a clear article error produces `pattern_type` containing articles.
- Lesson generation: curriculum JSON validates; `grammar_focus` is consistent with the injected milestone; no native-language learner-facing strings.

**Regression** — "this exact failure does not come back."

Seed from known product risks (no production traffic required for v1):

- L1 leakage (English explanation in a Spanish-immersion lesson)
- Missing `json:lesson_turn` / truncated fence
- Invented milestone not in the injected roadmap
- Duplicate or empty `exit_criteria`
- Schema repair path: first completion invalid, second must succeed *or* job fails cleanly (already unit-tested — keep one live case)

**Calibration** — 20–30 items with **human** labels for judge agreement only. Do not use these as the regression gate until agreement is measured.

### 5.2 Case file format

One YAML (or JSON) file per case, checked in under `evals/cases/`.

```yaml
id: lesson_chat_l1_leakage_es_001
suite: regression
mode: lesson          # onboarding | lesson | lesson_generation
skill: exercise_tutor
locale:
  native: en
  target: es
input:
  system_from_skills: true
  context_fixture: fixtures/learner_a2_travel_es.json
  user_message: "I go to store yesterday"
checks:
  deterministic:
    - extract_lesson_turn
    - no_english_learner_facing   # policy helper, not a judge
  judge:
    rubric: lesson_turn_v1
    expect:
      immersion: pass
      correction_accuracy: pass
      pedagogy: pass
notes: "English user turn is allowed; tutor must stay in Spanish."
```

Fixtures are anonymized. No real emails, no full production transcripts in git.

### 5.3 Runner

`evals/run.py` (or `apps/backend` console script):

1. Load cases (filter by `suite`, `mode`, `id`).
2. Assemble the same system instruction + context the API would (`get_system_instruction`, language policy block, profile/mistakes fixtures).
3. Call Gemini **once per case** (chat or lesson model as in production). Optional `--replay` from saved completions to debug judges without re-spending.
4. Run deterministic checks.
5. If those pass and the case asks for a judge, run the judge.
6. Write `evals/results/<run_id>.json` plus a short markdown summary: pass/fail by suite, new regressions vs `--baseline`.

See §5.4 for how replay runs in GitHub Actions. Live Gemini runs stay manual / nightly, tagged with model id and skill git sha.

### 5.4 CI (GitHub Actions)

Offline evals are a **required CI gate** — not a local-only habit.

**Repo policy (as of Aug 2026)**

- Repository is **public** on GitHub — standard Linux Actions minutes are unlimited for public repos.
- **`main` is branch-protected:** changes land via **pull request** (solo contributor; no required reviewer approval).
- Offline replay evals run on every PR and on merge to `main`, alongside existing pytest / lint.

**Workflow** — `.github/workflows/ci.yml` (or a dedicated `evals.yml` invoked from it):

| Trigger | Jobs |
|---------|------|
| `pull_request` | pytest + `python -m evals.run --suite regression --replay` |
| `push` to `main` | same (confirms green state after merge) |

Constraints:

- **No `GEMINI_API_KEY` in CI** — replay fixtures only (§5.3 step 3 skipped).
- Failed replay = red check on the PR; merge blocked once the eval job is a required status check on `main`.
- Job output: pass/fail by suite in Actions logs; optional short summary artifact (`evals/results/` is gitignored — commit baselines under `evals/fixtures/replay/` or similar, not ephemeral run dirs).

**Updating replay fixtures** (when a skill / prompt / contract change is intentional):

1. Run live locally or nightly: `python -m evals.run --suite regression` (with API key).
2. If green and behavior is correct, record new completions + baseline in the **same PR** as the skill change.
3. CI replay then locks the new expected outputs.

Live Gemini is still required to validate tutor *quality* on skill edits; CI replay guards that extraction, deterministic checks, and fixtures stay consistent.

**Solo PR flow**

```text
feature branch → push → open PR → CI (pytest + evals --replay) → merge (self)
```

No second approver. The eval job is the automated reviewer for offline quality.

---



## 6. Judges

A judge is a scored rubric, not a vibe. Treat judge quality as its own product.

### 6.1 Rubrics (v1)

Keep four binary-or-3-point dimensions. Do not start with a 12-axis scorecard.

**`lesson_turn_v1`** (chat)

| Dimension | Pass | Fail |
|-----------|------|------|
| Immersion | Learner-facing text is in `target_language` | Switches to native for explanation |
| Correction accuracy | Named error is real; correction is usable | Invents an error or wrong form |
| Pedagogy | Asks / drills; does not dump a lecture | Monologue, "Good." and stop |
| Contract | Side-payload present and consistent with the prose | JSON contradicts the chat |

**`lesson_generation_v1`**

| Dimension | Pass | Fail |
|-----------|------|------|
| Schema | Already enforced in code — judge does not re-check | — |
| Groundedness | Goal, grammar, slots follow injected plan + mistakes | New milestone / random topic |
| Difficulty | Matches stated CEFR / lesson number | Obvious A1 for a B1 plan (or the reverse) |
| Immersion | Learner-facing strings in `target_language` | English labels for the learner |

**`onboarding_v1`**

| Dimension | Pass | Fail |
|-----------|------|------|
| Completeness | Profile has goal, level, time, both languages | Guessed or missing required fields |
| One-question rule | At most one question in the reply | Stacked interview |
| Roadmap honesty | Days and milestones match stated budget | Invented 90-day plan after "15 min / week" |

### 6.2 Implementation

- First version: one Gemini call with a **fixed** rubric prompt and structured JSON output (`scores`, `rationale`, `span` if any). Same repair-once pattern as lesson generation.
- DeepEval (or LangSmith) is optional. A 100-line judge module is enough; adopt a library only if it reduces rubric drift.
- Store judge prompt + rubric version in the result file. A rubric change is a new version (`lesson_turn_v2`); do not silently compare v1 scores to v2.

### 6.3 Stability (do this before trusting the judge)

| Check | How | Gate |
|-------|-----|------|
| Human agreement | Double-label calibration set; report % agree and Cohen's κ per dimension | Informational until κ / agree is documented |
| Self-consistency | Re-judge the same completion 3 times | Flag dimensions with flips |
| Non-determinism of the *tutor* | Optional: generate 3 tutor replies, judge each | Understand variance; regression still uses one seeded or one-shot run |

If agreement is poor on a dimension, **drop the dimension** from the ship gate. A missing metric is better than a theatrical one.

---



## 7. Online quality signals

Infra metrics stay in Prometheus. Quality events are product data.

### 7.1 User signals

| Signal | Capture | Persist |
|--------|---------|---------|
| Thumbs up / down | Optional control on assistant bubbles (lesson + onboarding) | `quality_events` (`turn`, `session_id`, `message_id`, `value`, `created_at`) |
| Lesson CSAT | 1–5 or "useful / not" on **Finish lesson** (alongside existing free-text `learner_feedback`) | Same table (`kind=lesson_csat`) + keep text on `session_summary` |
| Implicit | `suggest_finish` accepted vs user finishes early; onboarding accept vs drop | Derive from existing tables — no new UI |

Do not block finish or chat on rating. Empty is allowed.

### 7.2 Sampled LLM-as-judge (production)

- After a lesson turn (or nightly batch): if the turn has `corrections` or thumbs-down, enqueue a judge job on a **sample** (e.g. 10% or all thumbs-down).
- Write `quality_events` with `kind=judge`, rubric version, scores, model id.
- Never judge the full raw prompt in logs (existing PII rule). Judge the stored assistant text + compact fixture (profile languages, lesson snippet).

### 7.3 Dashboard (decision-oriented)

One Grafana row or a SQL notebook.

Must answer, for a week:

1. Thumbs-down rate by `mode` (onboarding vs lesson)
2. Judge fail rate by dimension (immersion vs correction vs groundedness)
3. Existing: p95 latency, `llm_retries_total`, lesson job fail rate
4. Top mined failure tags (§8)

If a chart does not change what we do next week, delete it.

### 7.4 Schema sketch

```sql
CREATE TABLE quality_events (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    kind TEXT NOT NULL,          -- thumbs | lesson_csat | judge
    surface TEXT NOT NULL,       -- onboarding | lesson | lesson_generation
    session_id UUID,
    message_id UUID,
    lesson_id UUID,
    value JSONB NOT NULL,        -- { "thumb": -1 } | { "csat": 4 } | { "rubric": "...", "scores": {} }
    created_at TIMESTAMPTZ NOT NULL
);
```

---



## 8. Failure mining → regression cases

### 8.1 Sources (v1)

| Source | Tutor-failure hint |
|--------|-------------------|
| `quality_events` thumbs-down / low CSAT | User rejected the turn or lesson |
| `learner_feedback` on finish | "too hard", "wrong language", "more speaking" |
| `jobs` failed + `llm_retries` | Format / schema fragility |
| `mistakes` with high `occurrence_count` **and** repeated same `correction` | Tutor is not teaching it away (product, not only eval) |
| Structured logs `lesson_generation_failed`, `db_persist_failed` | Reliability, already monitored |

### 8.2 Miner

`evals/mine.py` (SQL + rules, no LLM required for v1):

1. Pull last N days of the sources above.
2. Cluster by crude tags: `immersion`, `schema`, `user_too_hard`, `job_fail`, `thumbs_down`.
3. Emit **candidate** YAML stubs under `evals/cases/inbox/` (not auto-merged into the gate).
4. A human (or later a judge) promotes a stub to `evals/cases/regression/` after stripping PII and writing the expected checks.

Weekly habit, not a daemon: run miner → pick 3–5 cases → add to suite → change skill or contract → re-run baseline.

---



## 9. Proposed layout

```text
.github/workflows/
  ci.yml                    # pytest + evals --replay on pull_request and push to main

evals/
  README.md                 # how to run, how to add a case, metric definitions
  run.py                    # suite runner
  mine.py                   # production → inbox stubs
  judges/
    lesson_turn_v1.md       # rubric (human-readable)
    lesson_turn_v1.py       # structured judge call
    lesson_generation_v1.md
    onboarding_v1.md
  cases/
    capability/
    regression/
    calibration/
    inbox/                  # miner output; not gated
  fixtures/                 # anonymized profiles, roadmaps, lesson snippets
  results/                  # gitignored run JSON + optional committed baseline
  docs/
    methodology.md          # sampling, noise, what we will not decide
```

Application touchpoints (only what online signals need):

- `POST /api/v1/quality/events` (or extend telemetry) for thumbs / CSAT
- Alembic migration for `quality_events`
- Finish-lesson request: optional `csat` next to `learner_feedback`
- Frontend: thumbs on assistant messages; optional CSAT on finish

No new LLM provider. Judge uses the existing Gemini client.

---

## 10. Relationship to other docs

| Doc | Relationship |
|-----|----------------|
| [monitoring_20260811.md](../monitoring_20260811/monitoring_20260811.md) §6 | This plan *is* that future layer |
| [deployment.md](../init/tech_requirements/deployment.md) | CI on PRs; branch protection on `main`; eval replay extends the MVP lint/test gate |
| [ai-api.md](../init/tech_requirements/ai-api.md) | Same call types and context assembly; evals replay them |
| [database.md](../init/tech_requirements/database.md) | Artifacts stay source of truth; `quality_events` is additive |
| [skills/README.md](../../../skills/README.md) | Skills are the system under test |

---

## 11. Implementation roadmap

### Phase 1 — Offline harness (capability + regression)

- [ ] Create `evals/` layout and `evals/README.md`.
- [ ] Write 15–25 capability cases (onboarding, lesson chat, lesson generation).
- [ ] Write 10–15 regression cases from known failure modes (§5.2).
- [ ] Implement `run.py`: skill load, fixture context, Gemini call, deterministic checks, JSON/markdown report.
- [ ] Commit a `--replay` baseline so CI runs without an API key.
- [ ] Add `.github/workflows/ci.yml`: pytest + `evals.run --suite regression --replay` on `pull_request` and push to `main`.
- [ ] Enable the eval job as a **required status check** on `main` (branch protection).
- [ ] Document how to add a case in one page.

**Exit:** `python -m evals.run --suite regression --replay` is green on `main`; a PR that breaks a regression case shows a failed check before merge.

### Phase 2 — Judges + methodology

- [ ] Rubric markdown + structured judge for `lesson_turn_v1` and `lesson_generation_v1`.
- [ ] Label a 20–30 item calibration set (human).
- [ ] Measure judge–human agreement and 3× self-consistency; write results in `evals/docs/methodology.md`.
- [ ] Drop or demote dimensions that are unstable.
- [ ] Wire judge into `run.py` **after** deterministic checks.
- [ ] Tag a baseline (`model`, `skill_sha`, `rubric_version`).

**Exit:** methodology doc states what a noisy metric must not decide; live suite can be run by hand.

### Phase 3 — Online signals

- [ ] `quality_events` migration + API.
- [ ] Thumbs on assistant messages; optional CSAT on finish.
- [ ] Prometheus counters for thumbs and CSAT (low cardinality: `surface`, `value`).
- [ ] Sampled production judge on thumbs-down / corrections (batch is fine).
- [ ] One weekly query or Grafana row (§7.3).

**Exit:** one week of real events can be queried.

### Phase 4 — Mine → regress → fix

- [ ] `mine.py` from `quality_events`, finish feedback, failed jobs, retries.
- [ ] Inbox → human promote → `cases/regression`.
- [ ] Weekly ritual: 3–5 new cases or an explicit "nothing to add."
- [ ] One worked example in `evals/docs/methodology.md` (failure → case → skill/contract change → suite green).

**Exit:** the loop has been run once end-to-end on this repo.

### Phase 5 — Shareable slice (optional, for external review)

- [ ] Public or shareable write-up: problem, metric definitions, one chart, one regression story.
- [ ] Sanitized fixtures + 2–3 case files + runner README.
- [ ] Keep production keys and raw transcripts out.

**Exit:** a stranger can understand how we decide the tutor is good.

---

## 12. Success criteria

The plan is done when all of the following are true:

1. A skill or model change can fail CI/replay because a **regression case** failed — not only because a unit test with a mock failed.
2. We can point at a rubric version and an agreement number for the judge (or we have dropped the judge from the gate).
3. Production has at least one user quality signal (thumbs or CSAT) stored as data, not only chat text.
4. A failure from production has been turned into a checked-in regression case at least once.

The ultimate goal is not "we have evals." It is **better tutor behavior through cases we are willing to be graded on**.
