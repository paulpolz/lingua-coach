# Eval harness — how to run, add a case, and read the numbers.

Stranger-facing slice (problem, metrics, Grafana, L1-leakage loop):
[`docs/shareable.md`](docs/shareable.md).

From the **repo root**. Backend packages must be importable (`PYTHONPATH=apps/backend`).
PyYAML lives in backend `[project.optional-dependencies] dev`.

```bash
# Replay (CI / no API key) — this is the ship gate. Never calls Gemini
# (tutor or judge). Judges load evals/fixtures/replay/<id>.judge.json if
# present; otherwise scores are omitted.
PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay

# Live Gemini (local / nightly). Needs GEMINI_API_KEY. Judges run after
# deterministic pass when the case has checks.judge (default; --no-judge skips).
PYTHONPATH=apps/backend:. python -m evals.run --suite capability
PYTHONPATH=apps/backend:. python -m evals.run --suite regression
PYTHONPATH=apps/backend:. python -m evals.run --suite all          # capability + regression

# Calibration + agreement (not a ship gate)
PYTHONPATH=apps/backend:. python -m evals.run --suite calibration --replay --agreement
PYTHONPATH=apps/backend:. python -m evals.run --suite calibration --agreement --self-consistency 3
```

Use the backend venv if the host Python lacks deps:

```bash
PYTHONPATH=apps/backend:. uv run --project apps/backend python -m evals.run --suite regression --replay
```

Other flags: `--mode onboarding|lesson|lesson_generation`, `--id <case_id>`,
`--baseline evals/fixtures/baseline.json` (skipped if the file is missing),
`--judge` (default when `checks.judge` is set), `--no-judge`,
`--self-consistency [N]` (default N=3; live only), `--agreement`.

Calibration and inbox are **not** ship gates. `--suite all` does not load them.
`--suite inbox` / `--suite calibration` run those folders but a check failure does not exit 1
(harness errors still do). First calibration `labels:` are **author-proposed**
pending independent double-label — see `evals/docs/methodology.md`.

Results: `evals/results/<run_id>.json` (gitignored) plus a markdown summary on stdout.
Each run is tagged with `model`, `skill_sha` (git tree of `skills/` at HEAD, else
repo HEAD), and `rubric_version` (`v1`; per-case judge uses `lesson_turn_v1` etc.).
Exit 1 if any **gated** case fails (capability / regression, after `expect_fail`).
Judge scores never change that exit code.

## Enable the required GitHub check

CI (`.github/workflows/ci.yml`) should run the same replay command on pull requests and
`push` to `main`. After the **first green run on `main`**, in GitHub:
**Settings → Branches → `main` → Require status checks → add the evals replay job**.
A workflow cannot be required until it has run once.

## Add a case

1. Anonymized JSON fixture under `evals/fixtures/` (no emails, no production transcripts).
2. YAML under `evals/cases/capability/` or `evals/cases/regression/` (see contract below).
3. Replay file `evals/fixtures/replay/<id>.json` so CI can run without Gemini.
4. Do not put miner stubs in the gate — they belong in `evals/cases/inbox/`
   (`suite: inbox`). Promote after stripping PII (see Failure mining below).

### YAML

```yaml
id: lesson_chat_l1_leakage_es_001   # must match replay filename stem
suite: regression                   # capability | regression | calibration | inbox
mode: lesson                        # onboarding | lesson | lesson_generation
locale:
  native: en
  target: es                        # required for immersion checks; ISO-ish / aliases ok
input:
  system_from_skills: true          # always assembled via prompt_assembly (production)
  context_fixture: fixtures/learner_a2_travel_es.json   # path relative to evals/
  user_message: "I go to store yesterday"               # omitted for lesson_generation
  # history: []                     # optional prior turns; do NOT duplicate user_message
checks:
  deterministic:
    - extract_lesson_turn
    - no_english_learner_facing
  judge:
    rubric: lesson_turn_v1          # lesson_turn_v1 | lesson_generation_v1 | onboarding_v1
# labels:                           # calibration only — author-proposed pass/fail per dimension
#   immersion: pass
expect_fail: false                  # true → case PASSES if a listed check fails
notes: "English user turn is allowed; tutor must stay in Spanish."
```

Optional `input.replay_from: <other_id>` reuses `fixtures/replay/<other_id>.json`
(used by calibration twins). A rubric change is a new version file; never compare
v1 scores to v2.

`expect_fail: true` is for known-bad replay completions (the check must still catch the bug).
If those checks unexpectedly pass, the case **fails**. Unknown check names are always a
case error (not inverted).

### Replay file `evals/fixtures/replay/<id>.json`

```json
{ "raw_completion": "…full model text including fenced json:* blocks…" }
```

Schema-repair cases store both attempts; **checks run on the last string**:

```json
{ "completions": ["{not valid}", "{…valid LessonCurriculum json…}"] }
```

### Fixture JSON (relative to `evals/`)

Passed into `prompt_assembly`. Useful keys:

| Mode | Fields |
| --- | --- |
| onboarding | optional `history`; languages from `locale` (or fixture `native_language` / `target_language`) |
| lesson | `curriculum` (or `lesson.payload.curriculum`), `goal_outcome` / `target_level` / `learner_profile`, `due_mistakes` (`pattern_type`, `example_text`), optional `history` |
| lesson_generation | `generation_context` **or** a flat snapshot: `roadmap`, `goal_outcome`, `native_language`, `due_mistakes` / `open_mistakes`, optional `lesson_number`. Runner builds the same JSON blob production dumps. Roadmap is required for `grammar_focus_aligned` / `invented_milestone`. |

Lesson chat contents match production: leading user turn = curriculum snippet + profile block, then history, then `user_message`. Onboarding is history + `user_message` only (no curriculum block).

Spanish-target immersion cases should not reuse English-target roadmaps.

## Update replay fixtures (intentional skill / prompt / contract change)

1. Run live: `PYTHONPATH=apps/backend python -m evals.run --suite regression` (API key required).
2. Confirm behavior is correct (not just that JSON parsed).
3. Copy new completions from `evals/results/<run_id>.json` → `evals/fixtures/replay/<id>.json`.
4. Refresh `evals/fixtures/baseline.json` `failed_ids` if the known-fail set changed.
5. Land replay + baseline **in the same PR** as the skill change. CI replay then locks the new outputs.

## Deterministic checks

| Name | Pass when |
| --- | --- |
| `extract_lesson_turn` | last valid `json:lesson_turn` parses |
| `extract_learner_profile` | last valid `json:learner_profile` parses |
| `extract_course_roadmap` | last valid `json:course_roadmap` parses |
| `no_english_learner_facing` | stripped learner-facing prose has no English explanation markers (`locale.target` ≠ `en`; JSON **keys** ignored) |
| `roadmap_target_language_matches` | roadmap `summary.target_language` matches `locale.target` |
| `pattern_type_articles` | a mistake/correction label contains `article` |
| `curriculum_valid` | completion JSON validates as `LessonCurriculum` |
| `grammar_focus_aligned` | `grammar_focus` overlaps fixture roadmap theme / milestone |
| `exit_criteria_nonempty_unique` | exit criteria non-empty, non-blank, unique |
| `invented_milestone` | `milestone_index` exists on the fixture roadmap |
| `one_question_rule` | at most one `?` in stripped prose |

## Judges (informational — not the CI gate)

Default: after deterministic checks, if `checks.judge.rubric` is set, run one
Gemini `generate_json` with the fixed rubric markdown (repair-once, same pattern
as lesson generation). `--replay` never calls that API. `--no-judge` skips
live and canned scores.

| Rubric | Dimensions |
| --- | --- |
| `lesson_turn_v1` | immersion, correction_accuracy, pedagogy, contract |
| `lesson_generation_v1` | groundedness, difficulty, immersion (schema is deterministic only) |
| `onboarding_v1` | completeness, one_question_rule, roadmap_honesty |

`--self-consistency 3` re-judges the same completion three times (live) and
flags dimension flips. `--agreement` compares scores (or canned `.judge.json`)
to `labels:` and prints % agree and Cohen’s κ per dimension.

See `evals/docs/methodology.md` and `evals/cases/calibration/README.md`.

Judges (immersion / correction / pedagogy scores) are **informational**, not this CI gate.

## Metrics (what a number is for)

Definitions from the quality-loop spec — stable enough to compare week to week.

| Metric | Meaning | Decision |
| --- | --- | --- |
| Replay / capability pass | Deterministic checks green on the suite | Ship or block a skill/prompt/model change |
| Regression vs baseline | Zero **new** gated failures vs `baseline.json` | A fix that breaks another case still fails the gate unless accepted (`expect_fail` / baseline update) |
| `immersion_pass_rate` | `no_english_learner_facing` (+ later judge) | Rewrite tutor language policy / skill |
| `groundedness` | `invented_milestone` + `grammar_focus_aligned` | Tighten generation contract |
| Judge agreement / self-consistency | Calibration `labels:` vs judge; `--agreement` / `--self-consistency` | Do not put a noisy dimension in the ship gate until κ / agree ≥ ~0.7 and double-label is documented |

Online thumbs / CSAT are not computed here. Infra latency and `llm_retries_total` are not quality.

## Online quality signals (frontend + batch judge)

Production user ratings land in `quality_events` via the authenticated API below.
Do **not** call Gemini on the chat SSE path. Nightly/local batch: `evals.judge_online`.

### Frontend API contract (locked)

Clerk session, same `Authorization: Bearer` as other `/api/v1` routes (not the unauthenticated telemetry endpoint).

**Thumbs** (assistant bubbles after SSE `done`, fire-and-forget). `204` on success:

```http
POST /api/v1/quality/events
```

```json
{
  "kind": "thumbs",
  "surface": "lesson",
  "session_id": "<uuid>",
  "message_id": "<uuid>",
  "lesson_id": "<uuid or null>",
  "value": { "thumb": 1 }
}
```

- `surface`: `onboarding` | `lesson` | `lesson_generation`
- `value.thumb`: `1` (up) or `-1` (down)
- Onboarding: omit `lesson_id` (`null`) and pass the onboarding `session_id` + assistant `message_id`

**Lesson CSAT** — either the same endpoint or finish:

```json
{
  "kind": "lesson_csat",
  "surface": "lesson",
  "session_id": "<uuid or null>",
  "message_id": null,
  "lesson_id": "<uuid>",
  "value": { "csat": 4 }
}
```

```http
POST /api/v1/lessons/{id}/finish
```

```json
{ "learner_feedback": "optional text", "csat": 4, "completed_slot_ids": [] }
```

`csat` is optional int `1–5`. Omit or send without it; finish still succeeds. Free-text `learner_feedback` still goes on `session_summary` as today. CSAT is also stored as `quality_events.kind=lesson_csat`.

### Batch production judge

```bash
PYTHONPATH=apps/backend:. python -m evals.judge_online
PYTHONPATH=apps/backend:. python -m evals.judge_online --limit 25
```

Reads unjudged `judge_candidate` rows (10% of lesson turns with corrections, plus all thumbs-down that still had a snapshot) and thumbs-down snapshots, calls Gemini with the same rubrics as `evals/judges/*`, writes `kind=judge` (rubric version, scores, model id). **Not** invoked from chat SSE.

If `GEMINI_API_KEY` is unset, the script prints a skip message and exits 0.

## Failure mining (weekly)

SQL + rules, no LLM. Writes **candidate stubs** under `evals/cases/inbox/`
(`suite: inbox`). That folder is **ungated**: `--suite regression` and
`--suite all` do not load it. Inbox YAML is gitignored until a human promotes it.

```bash
# Requires --database-url or DATABASE_URL (same as the backend). Fail-loud if missing.
PYTHONPATH=apps/backend:. python -m evals.mine
PYTHONPATH=apps/backend:. python -m evals.mine --days 7 --limit 20 --out evals/cases/inbox

# Counts only — no files
PYTHONPATH=apps/backend:. python -m evals.mine --dry-run --database-url "$DATABASE_URL"
```

Sources (last N days): `quality_events` thumbs-down and CSAT ≤ 2, finish
`learner_feedback`, failed `jobs`, `mistakes` with high `occurrence_count` and
the same `correction`. `llm_retries` / structured logs are skipped (not in SQL).

Crude tags: `immersion`, `schema`, `user_too_hard`, `job_fail`, `thumbs_down`.

**Ritual:** run the miner once a week. Pick 3–5 stubs to promote, or write
“nothing to add.” Stubs truncate user text and strip emails / UUIDs; still treat
them as production-derived.

### Promote inbox → regression

1. Copy `evals/cases/inbox/<id>.yaml` → `evals/cases/regression/<new_id>.yaml`.
2. Strip remaining PII. Replace `user_message` (`<fill on promote>`) with an
   anonymized line. Do not paste a full production transcript.
3. Set `suite: regression`. Move `suggested_checks` into `checks.deterministic`.
4. Point `input.context_fixture` at anonymized JSON under `evals/fixtures/`.
5. Add `evals/fixtures/replay/<new_id>.json`.
6. Confirm the gate:

   ```bash
   PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay
   ```

Worked example (L1 leakage, already in-repo): `evals/docs/methodology.md`.
Details: `evals/cases/inbox/README.md`.
