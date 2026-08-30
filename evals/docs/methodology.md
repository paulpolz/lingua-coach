# Eval methodology

How we sample, how noisy the numbers are, and **what we will not decide** from a
thin metric. Rubric identity is the filename (`lesson_turn_v1`). A rubric edit
is a new file (`lesson_turn_v2`); we never silently compare v1 scores to v2.

## Sampling

Offline cases are **hand-authored**, not a random draw of production traffic.

| Suite | What it is | Ship gate? |
| --- | --- | --- |
| Capability | Gold “the agent can still do the job” | Deterministic checks must pass |
| Regression | Known failure modes (and their gold pairs) | Zero **new** gated failures vs last tagged baseline |
| Calibration | 20–30 items with human (for now: author) labels | No. `--suite regression` does not load them |
| Inbox | `evals.mine` stubs (`suite: inbox`) | No until a human promotes them. `--suite regression` does not load this folder |

Replay fixtures freeze one completion per case so CI is deterministic. Live
Gemini is manual / nightly. Result JSON is tagged with:

- `model` — judge / lesson JSON model (`GEMINI_MODEL_LESSON`; chat uses `model_chat`)
- `skill_sha` — **git tree SHA of `skills/` at HEAD** (`git rev-parse HEAD:skills`).
  If that ref is missing, we store repo `HEAD` and set `skill_sha_source` to
  `repo_head` instead of `skills_tree`.
- `git_sha` — repo HEAD commit
- `rubric_version` — generation tag (`v1`). Per-case judge blobs also store the
  concrete file (`lesson_turn_v1`, …)

Inbox stubs from mining are not gated until a human promotes them to
`cases/regression/` after stripping PII.

## Offline gates (spec §4)

- **Capability:** all **deterministic** checks must pass. Judge scores are
  informational until agreement on the calibration set is ≥ ~0.7 (κ or % agree,
  documented here after independent double-label).
- **Regression:** **zero** new failures vs last tagged baseline
  (`evals/fixtures/baseline.json`). A change that fixes one case and breaks
  another fails the gate unless the baseline / `expect_fail` set is updated in
  the same PR.

`--replay` never calls Gemini — not for the tutor, not for judges. CI is
`python -m evals.run --suite regression --replay` with **no API key**.

## Judges (informational)

Judges run **after** deterministic checks, only when `checks.judge.rubric` is
set. They do **not** flip `passed` or the process exit code.

On gated suites (capability / regression), a live judge is skipped if
deterministic checks failed (do not spend tokens on unusable output).
Calibration still scores known-bad completions so fail labels can be measured.

`--replay` loads `evals/fixtures/replay/<id>.judge.json` when present; otherwise
judge scores are omitted (`source: skipped`).

### Dimensions (v1)

| Rubric | Dimensions (pass/fail) |
| --- | --- |
| `lesson_turn_v1` | Immersion, Correction accuracy, Pedagogy, Contract |
| `lesson_generation_v1` | Groundedness, Difficulty, Immersion (schema is **not** re-checked) |
| `onboarding_v1` | Completeness, One-question rule, Roadmap honesty |

### Stability (before any dimension becomes a gate)

| Check | How | Rule |
| --- | --- | --- |
| Human agreement | Double-label the calibration set; `% agree` and Cohen’s κ per dimension | Informational until documented; target ~0.7 |
| Self-consistency | `--self-consistency 3` on the same completion (live only) | Flag dimension flips; drop unstable dimensions rather than theatrical scores |

`--agreement` prints those numbers against `labels:` (live scores or canned
judge JSON). First calibration labels are **author-proposed**. Independent
double-label is required before any judge dimension becomes a ship gate.

Until that happens, treat live κ / % agree as tooling output, not a quality
claim. A few canned `.judge.json` files exist so the agreement CLI can be
exercised without an API key (N is tiny; do not cite those κ values as
calibration results).

## Noise / non-determinism

Replay freezes one completion so CI does not move. Live tutor and live judge
calls are non-deterministic. Self-consistency (repeat-3) is the check for
**judge** noise. Optional “generate 3 tutor replies” is out of scope here;
regression still uses one seeded / one-shot replay.

If agreement is poor on a dimension, **drop it from any future gate**. A missing
metric is better than a theatrical one.

## What we will not decide

- Do not rewrite a skill because thumbs dropped on N < 30.
- Do not switch models because one judge run moved 3 points.
- Do not treat `llm_retries_total` as quality — it is format fragility.
- Do not put judge scores on the CI fail path before independent double-label
  and agreement ≥ ~0.7 are written in this file.
- Do not compare `lesson_turn_v1` scores to `lesson_turn_v2`.

## Worked example — L1 leakage loop (run once in-repo)

This is the in-repo “loop run once.” It uses a **known failure mode** and
checked-in fixtures, not a fake week of production traffic or real learner PII.

### 1. Failure

Spanish-immersion lesson (`native: en`, `target: es`). The learner writes
English (`I go to store yesterday`). A bad tutor turn explains grammar **in
English** (`The past tense of go is went. You should say… In English this is
simple past.`). That is L1 leakage: `exercise_tutor.md` already says speak
only `target_language` in learner-facing text and use L1 solely to predict
interference.

Online, the miner would tag this `thumbs_down` + `immersion` (thumbs-down
snapshot whose assistant text fails `no_english_learner_facing`, or finish
feedback like “wrong language”). Stub would land in `evals/cases/inbox/`
with `suite: inbox` — still ungated.

### 2. Promote to regression (already done)

| File | Role |
| --- | --- |
| `evals/cases/regression/lesson_chat_l1_leakage_es_001.yaml` | Gold: tutor stays in Spanish. `expect_fail: false`. |
| `evals/cases/regression/lesson_chat_l1_leakage_es_001_caught.yaml` | Known-bad replay. `expect_fail: true` so CI goes red if the immersion check is removed. |
| `evals/fixtures/replay/lesson_chat_l1_leakage_es_001.json` | Anonymized good completion. |
| `evals/fixtures/replay/lesson_chat_l1_leakage_es_001_caught.json` | Anonymized English lecture + valid `json:lesson_turn` fence. |
| `evals/fixtures/learner_a2_travel_es.json` | Shared anonymized learner snapshot. |

Deterministic gate: `extract_lesson_turn` then `no_english_learner_facing`.
Calibration twin `cal_lesson_chat_l1_leakage_es_001_caught` holds
author-proposed judge labels (immersion fail, pedagogy fail) — informational
only.

### 3. Hypothetical skill / contract fix (not applied here)

If live traffic started reproducing the `_caught` completion, a skill tweak
would tighten `skills/exercise_tutor.md` “Language of the lesson”: e.g. an
explicit ban on English metalanguage (`this means`, `you should say`, `in
English`) when `target_language ≠ en`, plus “if the learner writes L1, still
reply only in the target.” No pedagogy rewrite is in this change — the
regression pair already locks the contract. A real fix lands in the **same
PR** as updated replay fixtures if the gold completion string changes.

### 4. Suite green

```bash
PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay
```

`--suite regression` never loads `evals/cases/inbox/`. After promote, the
gated pair is 12 regression cases; the `_caught` case **passes** because
`no_english_learner_facing` fails as expected (`expect_fail: true`). A skill
edit that leaks English on the gold case fails CI.
