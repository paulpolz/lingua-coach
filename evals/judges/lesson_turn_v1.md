# lesson_turn_v1

Binary (pass / fail) rubric for a single **lesson chat** tutor turn. Score only the learner-facing reply plus its `json:lesson_turn` side-payload. Do not re-score HTTP success, token counts, or retries.

The user may write in their native language. That is allowed. Judge the **tutor**.

## Immersion

- **Pass:** Learner-facing prose is in `target_language`. Brief target-language recasts of a native-language user turn are fine.
- **Fail:** The tutor switches to the native language to explain, lecture, or translate (“this means”, “in English”, “you should say”). Isolated loanwords or proper names are not a fail.

## Correction accuracy

- **Pass:** Named errors are real in the user’s last turn; the correction is a usable form. Empty `corrections` / `mistakes` is a pass when the user turn is already grammatical.
- **Fail:** Invents an error that is not present, or gives a wrong form / wrong pattern.

## Pedagogy

- **Pass:** Asks or drills; keeps the learner producing. A short recast plus one prompt is enough.
- **Fail:** Monologue / grammar lecture with no next move, or “Good.” / “Bien.” and stop.

## Contract

- **Pass:** A `json:lesson_turn` block is present and consistent with the prose (same error, same correction, no contradicting `suggest_finish`).
- **Fail:** Missing or truncated side-payload, or JSON that contradicts the chat.

## Output

Return one JSON object only:

```json
{
  "scores": {
    "immersion": "pass",
    "correction_accuracy": "pass",
    "pedagogy": "pass",
    "contract": "pass"
  },
  "rationale": {
    "immersion": "one short sentence",
    "correction_accuracy": "one short sentence",
    "pedagogy": "one short sentence",
    "contract": "one short sentence"
  },
  "span": "optional shortest quote that justifies a fail, else null"
}
```

Each score must be exactly `"pass"` or `"fail"`.
