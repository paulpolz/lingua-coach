"""Loads skills/*.md as system instructions. Pedagogy stays in those files."""

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
