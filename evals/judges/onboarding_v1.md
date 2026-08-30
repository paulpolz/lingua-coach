# onboarding_v1

Binary (pass / fail) rubric for an **onboarding** interview or handoff turn. Score the learner-facing reply plus any `json:learner_profile` / `json:course_roadmap` blocks.

Mid-interview turns are allowed to omit the profile. Do not fail Completeness for a mid-interview that correctly asks the next question instead of guessing.

## Completeness

- **Pass:** When this turn emits a profile, it has goal, level, time budget, and both languages, grounded in what the learner said. Mid-interview with **no** profile (still collecting) is a pass.
- **Fail:** Emits a profile that guesses or drops required fields, or emits a profile before languages / goal / level / time are known.

## One-question rule

- **Pass:** At most one question in the learner-facing reply (one `?` is the usual signal). A handoff that presents a plan and asks one confirmation question is a pass.
- **Fail:** Stacked interview — two or more questions in one reply.

## Roadmap honesty

- **Pass:** If a roadmap is present, days and milestones match the stated time budget (e.g. ~25 min × 4 days/week → tens of plan days, not a 90-day grind). Mid-interview with no roadmap is a pass.
- **Fail:** Invents a 90-day intensive plan after “15 minutes / week”, or ignores an explicit horizon the learner gave.

## Output

Return one JSON object only:

```json
{
  "scores": {
    "completeness": "pass",
    "one_question_rule": "pass",
    "roadmap_honesty": "pass"
  },
  "rationale": {
    "completeness": "one short sentence",
    "one_question_rule": "one short sentence",
    "roadmap_honesty": "one short sentence"
  },
  "span": "optional shortest quote that justifies a fail, else null"
}
```

Each score must be exactly `"pass"` or `"fail"`.
