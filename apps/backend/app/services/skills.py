"""Loads skills/*.md as system instructions and holds the backend output contracts.

The contracts tell the model how to hand structured data back (hidden JSON fences
or a bare JSON object). They are wiring, not pedagogy.
"""

from __future__ import annotations

import functools
from pathlib import Path

from app.config import settings

_MODE_SKILLS = {
    "onboarding": ["onboarding_interviewer", "course_composer"],
    "lesson": ["exercise_tutor"],
}

_VOCAB_REVIEW_MARKERS = ("vocab_review", "vocabulary_review", "weekend_vocab", "weekly_vocab", "vocab review")


@functools.lru_cache(maxsize=None)
def load_skill(name: str) -> str:
    return (Path(settings.skills_dir) / f"{name}.md").read_text(encoding="utf-8")


def should_include_vocab_formats(curriculum: dict | None) -> bool:
    """True on week-end vocab-review lessons; those append vocabulary_practice_formats.md."""
    for slot in (curriculum or {}).get("slots") or []:
        text = f"{slot.get('id', '')} {slot.get('label', '')}".lower().replace("-", "_")
        if any(marker in text for marker in _VOCAB_REVIEW_MARKERS):
            return True
    return False


def get_system_instruction(mode: str, *, include_vocab_formats: bool = False) -> str:
    names = list(_MODE_SKILLS[mode])
    if mode == "lesson" and include_vocab_formats:
        names.append("vocabulary_practice_formats")
    return "\n\n---\n\n".join(load_skill(name) for name in names)


ONBOARDING_EXTRACTION_CONTRACT = """\
---
Backend output contract (hidden from the user):

Ask at most one question per reply.

1. When the interview is complete, append one fenced block with the learner profile
   from "Output: learner profile" as JSON. It must include languages.native and
   languages.target:

```json:learner_profile
{ ... }
```

   Re-emit it if the learner later changes languages, goal, level, time, or focus.

2. Whenever you present a new or revised roadmap the learner could accept, append the
   full course_roadmap object from "Output: course_roadmap (JSON)" (include
   summary.target_language). Keep the markdown roadmap in the reply as well:

```json:course_roadmap
{ ... }
```

   Once a roadmap exists, every reply that applies concrete plan feedback must carry a
   full updated block.

3. Never mention these blocks or ask the learner to read JSON.
"""

LESSON_EXTRACTION_CONTRACT = """\
---
Backend output contract (hidden from the user):

End every lesson reply with exactly one block:

```json:lesson_turn
{
  "corrections": [{ "span": "...", "correction": "...", "type": "grammar|vocab|...", "note": "..." }],
  "tips": ["..."],
  "plan_updates": null,
  "suggest_finish": false,
  "mistakes": [{ "pattern_type": "...", "example_text": "...", "correction": "..." }],
  "completed_task_ids": []
}
```

- corrections / tips: only for this turn; empty arrays otherwise.
- plan_updates: null unless the learner asks for a concrete plan change. Then include only
  the changed fields among goal_summary, level, time_budget, topics, vocab_priorities,
  target_plan_days, grammar_mastery.
- suggest_finish: true only once every curriculum slot and exit criterion is done.
- mistakes: one entry per recurring-worthy error pattern; pattern_type is a short stable label.
- completed_task_ids: tasks you mark done in this turn.

On the first coaching turn (or when revising the agenda) also emit, and say the agenda in prose:

```json:lesson_plan
{ "tasks": [{ "id": "warmup", "label": "Warm-up", "minutes": 5 }] }
```

Align task ids with curriculum.slots[].id. Never mention these blocks to the learner.
"""

REPORT_PATCH_CONTRACT = """\
---
Backend output contract: reply with one JSON object only, no prose or fences:

{ "ops": [ { "report_type": "progress|errors_log|roadmap|four_week_plan",
             "op": "append_entry|patch_section",
             "section_id": "existing_section_id",
             "markdown": "..." } ] }

Use append_entry for dated log lines and patch_section to replace a whole section.
section_id must match an existing <!-- section:ID --> marker. ops may be empty.
"""

LESSON_GENERATION_CONTRACT = """\
---
Backend output contract: reply with one JSON object only, no prose or fences:

{
  "lesson_goal": "one sentence",
  "grammar_focus": "point + why it matters",
  "vocab_theme": "theme label",
  "milestone_index": 0,
  "slots": [{ "id": "warmup", "label": "...", "exercise_set": "planned drills" }],
  "input_task": { "type": "reading", "topic": "...", "focus": "what to notice" },
  "goal_specific_task": { "label": "...", "format": "email|message|summary|..." },
  "exit_criteria": ["..."]
}
"""
