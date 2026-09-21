"""Shared Gemini prompt assembly for chat, lesson generation, and evals.

Production routes still load ORM/DB, then call these helpers. The eval runner
loads YAML fixtures and calls the same functions so assembled strings cannot
drift from the API. Pedagogy stays in `skills/*.md`; this module only
concatenates skill text, extraction contracts, language policy, and compact
context blocks.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from app.services.languages import language_policy_block
from app.services.skills import (
    LESSON_EXTRACTION_CONTRACT,
    LESSON_GENERATION_CONTRACT,
    ONBOARDING_EXTRACTION_CONTRACT,
    get_system_instruction,
)


def onboarding_system_instruction(native: str | None, target: str | None) -> str:
    policy = language_policy_block(surface="onboarding", native=native, target=target)
    return f"{get_system_instruction('onboarding')}\n\n{ONBOARDING_EXTRACTION_CONTRACT}\n\n{policy}"


def lesson_system_instruction(
    native: str | None, target: str | None, include_vocab: bool
) -> str:
    policy = language_policy_block(surface="lesson", native=native, target=target)
    return (
        f"{get_system_instruction('lesson', include_vocab_formats=include_vocab)}\n\n"
        f"{LESSON_EXTRACTION_CONTRACT}\n\n{policy}"
    )


def lesson_generation_system_instruction(native: str | None, target: str | None) -> str:
    policy = language_policy_block(
        surface="lesson_generation", native=native, target=target
    )
    return f"{get_system_instruction('lesson')}\n\n{LESSON_GENERATION_CONTRACT}\n\n{policy}"


def lesson_curriculum_snippet_from_payload(curriculum: dict | None) -> str:
    """Compact current-lesson block for lesson-chat `contents`.

    Same strings as the former `chat._lesson_curriculum_snippet` body.
    """
    curriculum = curriculum or {}
    if not curriculum:
        return "Current lesson curriculum: not yet generated (lesson is still generating)."

    slots = curriculum.get("slots") or []
    slots_text = (
        "\n".join(
            f"  - {s.get('id')}: {s.get('label')} — {s.get('exercise_set')}" for s in slots
        )
        or "  (none)"
    )
    exit_criteria = curriculum.get("exit_criteria") or []
    exit_text = "\n".join(f"  - {c}" for c in exit_criteria) or "  (none)"

    input_task = curriculum.get("input_task") or {}
    if input_task:
        input_text = (
            f"Input task: {input_task.get('type', '')} — "
            f"topic: {input_task.get('topic', '')}; "
            f"focus: {input_task.get('focus', '')}"
        )
        resource = input_task.get("resource") or {}
        if resource:
            notice = resource.get("notice_points") or []
            notice_text = "; ".join(str(n) for n in notice) if notice else "(none)"
            duration = resource.get("duration_sec")
            minutes = f"{int(duration) // 60} min" if duration else ""
            input_text += (
                f"\nListening resource (use this URL; do not invent another):\n"
                f"  id: {resource.get('id', '')}\n"
                f"  title: {resource.get('title', '')}\n"
                f"  url: {resource.get('url', '')}\n"
                f"  duration: {minutes}\n"
                f"  source: {resource.get('source', '')}\n"
                f"  captions: {resource.get('captions', '')}\n"
                f"  synopsis: {resource.get('synopsis', '')}\n"
                f"  notice_points: {notice_text}"
            )
    else:
        input_text = "Input task: (none)"

    goal_task = curriculum.get("goal_specific_task") or {}
    if goal_task:
        goal_task_text = (
            f"Goal-specific task: {goal_task.get('label', '')} "
            f"(format: {goal_task.get('format', '')})"
        )
    else:
        goal_task_text = "Goal-specific task: (none)"

    return (
        "Current lesson curriculum (lessons.payload.curriculum):\n"
        f"Lesson goal: {curriculum.get('lesson_goal', '')}\n"
        f"Grammar focus: {curriculum.get('grammar_focus', '')}\n"
        f"Vocab theme: {curriculum.get('vocab_theme', '')}\n"
        f"Slots:\n{slots_text}\n"
        f"{input_text}\n"
        f"{goal_task_text}\n"
        f"Exit criteria:\n{exit_text}"
    )


def _due_mistake_line(item: Any) -> str:
    if isinstance(item, Mapping):
        pattern = item.get("pattern_type")
        example = item.get("example_text")
    else:
        pattern = getattr(item, "pattern_type", None)
        example = getattr(item, "example_text", None)
    return f"  - {pattern}: {example}"


def lesson_profile_block_from_snapshot(
    native: str | None,
    target: str | None,
    goal: str | None,
    level: str | None,
    due_mistakes: Iterable[Any] | None,
) -> str:
    """Compact learner-profile context block — no DB access.

    `due_mistakes` is an iterable of mappings or objects with `pattern_type`
    and `example_text` (ORM `Mistake` rows or fixture dicts).
    """
    items = list(due_mistakes) if due_mistakes else []
    due_text = (
        "\n".join(_due_mistake_line(m) for m in items) if items else "  (none due)"
    )

    goal_s = goal if goal else "(not set)"
    level_s = level if level else "(not set)"
    native_s = native if native else "(not set)"
    target_s = target if target else "en"

    return (
        "Learner profile (compact):\n"
        f"Native language: {native_s}\n"
        f"Target language: {target_s}\n"
        f"Goal: {goal_s}\n"
        f"Level: {level_s}\n"
        f"Conduct this lesson only in {target_s}.\n"
        f"Weak patterns due for review:\n{due_text}"
    )


def build_generation_user_prompt(context: dict) -> str:
    """User-turn prompt for lesson JSON generation (same wrapping as production)."""
    return (
        "Generate the next lesson's curriculum for this learner, per the "
        "Generation rules above. Learner and plan context (JSON):\n"
        f"{json.dumps(context, default=str)}\n\n"
        "Pick one grammar focus and one vocab theme aligned to the current "
        "milestone; interleave due items from open_mistakes and prior_lessons "
        "before adding new material.\n"
        "input_assignment is chosen by the backend. If mode is listening, copy "
        "input_assignment.resource onto input_task.resource exactly (same id and "
        "url) and set input_task.type to listening. Do not invent a URL. If mode "
        "is reading, set input_task.type to reading and omit resource; write a "
        "150-300 word passage in chat later, not a fake listening task.\n"
        "Do not emit a speaking slot. Map any speaking activity on the weekly "
        "template to writing (email, message, summary, written dialogue). "
        "goal_specific_task.format must be a written format, never oral roleplay."
    )
