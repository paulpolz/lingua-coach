# Capability cases

Passing gold for deterministic checks (en native / es target).

- One YAML file per case; replay at `evals/fixtures/replay/<id>.json`.
- Shared snapshot: `evals/fixtures/learner_a2_travel_es.json` (plus roadmap and curriculum siblings).
- Generation `raw_completion` is a JSON **object string** (the curriculum), not a fenced chat reply.
- Mid-interview cases must not emit `json:learner_profile`.
