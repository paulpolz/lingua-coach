# lesson_generation_v1

Binary (pass / fail) rubric for a **lesson curriculum** JSON object. Schema validity is already enforced in code — **do not re-check** field types, required keys, or Pydantic errors.

Score pedagogy against the injected plan, profile CEFR / lesson number, and language policy.

## Groundedness

- **Pass:** Goal, grammar focus, milestone index, and slot themes follow the injected roadmap / due mistakes. No new milestone title or random topic.
- **Fail:** Invents a milestone, jumps to a grammar theme that is not in the current block, or abandons the stated travel / goal context.

## Difficulty

- **Pass:** Tasks match the stated CEFR and lesson number (A2 hotel role-play for an A2 travel plan).
- **Fail:** Obvious A1 “hola / me llamo” for a B1 (or even solid A2) plan, or B2+ subjunctive philosophy for an A2 article lesson.

## Immersion

- **Pass:** Learner-facing strings (goals, labels, exercise_set, exit_criteria) are in `target_language`. JSON **keys** may stay English.
- **Fail:** English labels or instructions aimed at the learner (“Warm-up: fill in the blanks”).

## Output

Return one JSON object only:

```json
{
  "scores": {
    "groundedness": "pass",
    "difficulty": "pass",
    "immersion": "pass"
  },
  "rationale": {
    "groundedness": "one short sentence",
    "difficulty": "one short sentence",
    "immersion": "one short sentence"
  },
  "span": "optional shortest quote that justifies a fail, else null"
}
```

Each score must be exactly `"pass"` or `"fail"`.
