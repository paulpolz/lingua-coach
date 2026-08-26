"""Loads agent skill markdown files as `system_instruction` text per chat mode.

Skills (`skills/*.md`) are pedagogy IP and the source of truth for what the
model should do — see skills/README.md. This module only *loads and
concatenates* those files per the orchestration table in
docs/tech_requirements/ai-api.md; it must never duplicate pedagogy content in
Python.

`ONBOARDING_EXTRACTION_CONTRACT` / `LESSON_EXTRACTION_CONTRACT` below are the
one exception: they are backend *wiring* instructions (how to format a
structured side-payload for the backend to parse), not pedagogy, so they live
in code and are appended after the skill text by the chat route.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.config import settings

# Mode -> ordered skill file stems, concatenated in this order for
# `system_instruction` (see ai-api.md "Orchestration" table).
_MODE_SKILLS: dict[str, list[str]] = {
    "onboarding": ["onboarding_interviewer", "course_composer"],
    "lesson": ["exercise_tutor"],
}

_LESSON_VOCAB_SKILL = "vocabulary_practice_formats"

# Week-end Format A/B drills (`vocabulary_practice_formats.md`) — not the
# daily `vocabulary` slot in the weekly template (~11% of a normal session).
_VOCAB_REVIEW_IDS = frozenset(
    {
        "vocab_review",
        "vocabulary_review",
        "weekend_vocab",
        "week_end_vocab",
        "weekly_vocab",
        "vocab-review",
    }
)
_VOCAB_REVIEW_LABEL_MARKERS = (
    "vocab review",
    "vocabulary review",
    "week-end vocab",
    "weekend vocab",
    "weekly vocab",
    "week end vocab",
)


class SkillLoadError(RuntimeError):
    """Raised when a required skill markdown file cannot be read."""


def _skills_dir() -> Path:
    return Path(settings.skills_dir)


@functools.lru_cache(maxsize=None)
def _read_skill_file(skills_dir: str, name: str) -> str:
    path = Path(skills_dir) / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillLoadError(f"Could not read skill file {name!r} at {path}: {exc}") from exc


def _is_vocab_review_item(item_id: str, label: str) -> bool:
    nid = item_id.strip().lower().replace("-", "_")
    if nid in _VOCAB_REVIEW_IDS:
        return True
    nlabel = label.strip().lower()
    return any(marker in nlabel for marker in _VOCAB_REVIEW_LABEL_MARKERS)


def should_include_vocab_formats(
    curriculum: Mapping[str, Any] | None = None,
    weekly_template: Mapping[str, Any] | None = None,
) -> bool:
    """True when today's lesson is a week-end vocab-review turn.

    Inspects `curriculum.slots` and optional `weekly_template.activities`.
    Daily `vocabulary` / `review` ids are not a match — those are the regular
    session blocks, not Format A/B drills (`vocabulary_practice_formats.md`).
    Lesson chat passes the result into `get_system_instruction`.
    """
    for slot in (curriculum or {}).get("slots") or []:
        if isinstance(slot, Mapping) and _is_vocab_review_item(
            str(slot.get("id") or ""), str(slot.get("label") or "")
        ):
            return True
    for activity in (weekly_template or {}).get("activities") or []:
        if isinstance(activity, Mapping) and _is_vocab_review_item(
            str(activity.get("id") or ""), str(activity.get("label") or "")
        ):
            return True
    return False


def get_system_instruction(mode: str, *, include_vocab_formats: bool = False) -> str:
    """Return concatenated skill markdown for a chat mode.

    `mode`: "onboarding" | "lesson". Lesson chat sets
    `include_vocab_formats` from `should_include_vocab_formats` (curriculum /
    weekly-template vocab-review signal). A no-op for other modes.
    """
    if mode not in _MODE_SKILLS:
        raise SkillLoadError(f"Unknown chat mode: {mode!r}")

    skill_names = list(_MODE_SKILLS[mode])
    if mode == "lesson" and include_vocab_formats:
        skill_names.append(_LESSON_VOCAB_SKILL)

    skills_dir = str(_skills_dir())
    return "\n\n---\n\n".join(_read_skill_file(skills_dir, name) for name in skill_names)


def clear_cache() -> None:
    """Test helper — drop the cached file contents (e.g. after monkeypatching
    `settings.skills_dir` or editing a skill file mid-test-run)."""
    _read_skill_file.cache_clear()


def load_skill(name: str) -> str:
    """Read a single skill markdown file by stem (e.g. `report_writer`)."""
    return _read_skill_file(str(_skills_dir()), name)


# --- Backend wiring instructions (not pedagogy) -----------------------------
#
# The model output is free-form conversational text. To hand structured
# artifacts back to the backend without a separate tool-call round trip, we
# ask the model to embed fenced JSON blocks with a recognizable info-string
# at the point in its reply where the corresponding skill produces that
# artifact. The backend parses these with a regex (app/services/extraction.py)
# and strips them from the text shown to the user / persisted to
# `chat_messages` — the surrounding natural-language reply (including any
# markdown roadmap presentation from course_composer.md) is left intact.
ONBOARDING_EXTRACTION_CONTRACT = """\
---
Backend output contract (follow exactly; this is not shown to the user):

Conversation rule: Never ask more than one question in a single reply.

1. Once the onboarding interview above is fully complete and you have\
 everything needed for the "Output: learner profile" section, include in\
 your reply a single fenced code block formatted exactly as:

```json:learner_profile
{ ... the learner_profile object as JSON (not YAML), using exactly the\
 fields from the "Output: learner profile" section. MUST include\
 `languages.native` and `languages.target` — do not emit this block without\
 both. ... }
```

Only include this block once the interview is genuinely complete — do not\
 emit a partial or guessed profile. You may re-emit an updated block on a\
 later turn if the user changes their languages, goal, level, time budget, or\
 focus areas.

2. Whenever you present a new or revised course roadmap the user could\
 accept (course_composer's chat presentation), also include, at the end of\
 the same reply, a single fenced code block formatted exactly as:

```json:course_roadmap
{ ... the full course_roadmap object as JSON, using exactly the fields from\
 "Output: course_roadmap (JSON)". Include `summary.target_language` (ISO\
 639-1 of the learning language); `summary.native_language` is optional. ... }
```

Keep the human-readable markdown roadmap presentation in your reply as\
 normal — the JSON block is in addition to it, not a replacement.

 After a course_roadmap has already been presented in this conversation:\
 any reply that incorporates the user's plan feedback (pace, milestones,\
 topics, weekly balance, horizon, or similar) MUST include a full updated\
 ```json:course_roadmap``` block — not prose-only. Ask a clarifying\
 question without regenerating only when the request is too ambiguous to\
 apply; once the user gives a concrete change, regenerate the full object.

3. Never mention these JSON blocks to the user, and never ask the user to\
 read or edit raw JSON — they are a backend integration detail.
"""

LESSON_EXTRACTION_CONTRACT = """\
---
Backend output contract (follow exactly; this is not shown to the user):

At the end of every reply during this lesson, include a single fenced code\
 block formatted exactly as:

```json:lesson_turn
{
  "corrections": [
    { "span": "...", "correction": "...", "type": "grammar|vocab|...", "note": "..." }
  ],
  "tips": ["..."],
  "plan_updates": null,
  "suggest_finish": false,
  "mistakes": [
    { "pattern_type": "...", "example_text": "...", "correction": "..." }
  ]
}
```

Rules for this block:

1. `corrections` — 0 or more corrections you made *in this turn* (the\
 learner's exact span, the corrected form, a short `type` label, and a\
 one-line `note`). Empty array if you made no corrections this turn.
2. `tips` — 0 or more short standalone tips for this turn (e.g. a usage\
 note not tied to a specific correction). Empty array if none.
3. `plan_updates` — `null` unless the learner's feedback this turn implies\
 a concrete change to their plan (e.g. "this is too easy/hard", "I want\
 more speaking practice", an explicit new deadline or pace). When present,\
 include only the fields that should change — any of `goal_summary`,\
 `level`, `time_budget`, `topics`, `vocab_priorities`, `target_plan_days`,\
 `grammar_mastery` — omitting fields that are not changing rather than\
 repeating their current values.
4. `suggest_finish` — `true` only once every planned exercise in the\
 current lesson curriculum (`curriculum.slots`) and its exit criteria are\
 done, per "Completion and exit criteria" above. Otherwise `false`. The\
 learner still explicitly finishes the lesson themselves — this is only a\
 signal.
5. `mistakes` — one entry per **named, recurring-worthy error pattern**\
 surfaced this turn (see "Mistake artifact" above) — not one entry per\
 uncorrected typo or every correction in `corrections`. `pattern_type` is a\
 short, stable taxonomy label (e.g. "missing articles", "irregular past")\
 so repeats of the same pattern match across turns and lessons;\
 `example_text` is the learner's own span/sentence; `correction` is\
 optional (one-line correct form). Empty array if no pattern-worthy error\
 occurred this turn.

Always include this block, exactly once, even when every field is\
 empty/null/false — this is how the backend knows the turn is complete.

6. On the first coaching turn of a lesson (and again only if you revise\
 the agenda), also include a fenced block:

```json:lesson_plan
{ "tasks": [ { "id": "warmup", "label": "Warm-up retrieval", "minutes": 5 } ] }
```

 Align `id` with `curriculum.slots[].id` when possible. `minutes` is an\
 approximate reference, not a countdown. Also write the same agenda in\
 ordinary chat prose so the learner can see it in the transcript.

7. When you confirm a task is finished, also include:

```json:task_update
{ "completed_task_ids": ["warmup"] }
```

 Only list tasks you are marking complete in *this* turn. Say so in prose\
 as well. Do not wait until the end of the lesson to emit updates.

 Never mention these JSON blocks to the user, and never ask them to read\
 or edit raw JSON — they are a backend integration detail.
"""

REPORT_PATCH_CONTRACT = """\
---
Backend output contract (follow exactly; this is not shown to the user):

Respond with a single JSON object only — no markdown, no prose, no code\
 fences, no surrounding text — matching exactly this shape:

{
  "ops": [
    {
      "report_type": "progress|errors_log|roadmap|four_week_plan",
      "op": "append_entry|patch_section",
      "section_id": "stable_section_id",
      "markdown": "markdown for that section or new entry"
    }
  ]
}

Rules:

1. Emit only ops for sections that actually changed this lesson.\
 Use `append_entry` to add a dated log line or new day entry inside a\
 section. Use `patch_section` to replace a whole named section (tables,\
 latest-session findings, pattern tracker).
2. `section_id` must match an existing `<!-- section:ID -->` marker in\
 that report. Unknown ids are ignored.
3. Do not rewrite an entire report. Keep deltas small.
4. `ops` may be an empty array if nothing in the reports should change.
"""

# Appended to the `exercise_tutor` skill text for the non-streaming lesson
# *generation* call (app/services/lesson_generation.py) — distinct from
# `LESSON_EXTRACTION_CONTRACT` above, which is for the (Phase 4) lesson
# *chat* stream. This call must return only the `curriculum` object (the
# canonical nested shape from database.md / exercise_tutor.md "Lesson
# payload" — not readiness §8's flat example, which the plan explicitly
# marks as superseded).
LESSON_GENERATION_CONTRACT = """\
---
Backend output contract (follow exactly; this is not shown to the user):

Respond with a single JSON object only — no markdown, no prose, no code\
 fences, no surrounding text — matching exactly this shape:

{
  "lesson_goal": "One sentence — what the learner will be able to do after",
  "grammar_focus": "Point + why it matters for their goal",
  "vocab_theme": "Theme label — not full word lists",
  "milestone_index": 0,
  "slots": [
    { "id": "warmup", "label": "string", "exercise_set": "Brief description of planned drills" }
  ],
  "input_task": { "type": "listening|reading", "topic": "string", "focus": "what to notice" },
  "goal_specific_task": { "label": "string", "format": "email|roleplay|..." },
  "exit_criteria": ["string"],
  "partner_session": null
}

Do not wrap this in a `version` / `curriculum` / `session_summary` envelope\
 — return only the curriculum object itself, with these exact field names.\
 `slots` and `exit_criteria` must each have at least one item.
"""
