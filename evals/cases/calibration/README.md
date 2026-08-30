# Calibration cases

20–30 items with **author-proposed** `labels:` (pass/fail per judge dimension).

These are **not** a CI / ship gate. `--suite regression` does not load this folder.
`--suite all` is capability + regression only.

First-pass labels were written by the eval author while building the harness.
They are **not** an independent double-label. Do not promote any judge dimension
to a ship gate until two humans have labeled this set and agreement is written
in `evals/docs/methodology.md`.

## How to run

```bash
# Replay: deterministic checks + canned judges only (no GEMINI_API_KEY)
PYTHONPATH=apps/backend:. python -m evals.run --suite calibration --replay --agreement

# Live judges (needs GEMINI_API_KEY). Optional 3× self-consistency:
PYTHONPATH=apps/backend:. python -m evals.run --suite calibration --agreement --self-consistency 3
```

Canned judge files (so `--agreement` works without an API key) live next to
replay completions as `evals/fixtures/replay/<id>.judge.json` for a few items.

Cases may set `input.replay_from: <other_case_id>` to reuse an existing
`fixtures/replay/<other_case_id>.json` completion.
