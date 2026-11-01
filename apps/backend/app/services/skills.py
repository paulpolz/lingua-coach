"""Loads skills/*.md as system instructions. Pedagogy stays in those files."""

from __future__ import annotations

import functools
from pathlib import Path

from app.config import settings

_MODE_SKILLS = {
    "onboarding": ["onboarding_interviewer", "course_composer"],
    "lesson": ["exercise_tutor"],
}


@functools.cache
def load_skill(name: str) -> str:
    return (Path(settings.skills_dir) / f"{name}.md").read_text(encoding="utf-8")


def get_system_instruction(mode: str) -> str:
    return "\n\n---\n\n".join(load_skill(name) for name in _MODE_SKILLS[mode])
