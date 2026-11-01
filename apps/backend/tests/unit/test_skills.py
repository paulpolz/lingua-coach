"""Skill loading."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.services.skills import get_system_instruction


def test_lesson_instruction_is_the_exercise_tutor_only() -> None:
    text = get_system_instruction("lesson")
    assert text.startswith("# Exercise Tutor")
    assert "vocabulary_practice_formats" not in text


def test_onboarding_instruction_joins_interviewer_and_composer() -> None:
    text = get_system_instruction("onboarding")
    assert text.index("# Onboarding Interviewer") < text.index("# Course Composer")


def test_retired_skill_file_is_gone() -> None:
    assert not (Path(settings.skills_dir) / "vocabulary_practice_formats.md").exists()


def test_skills_never_mention_speaking_slots_or_listening_rows() -> None:
    for path in Path(settings.skills_dir).glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "partner_session" not in text, path.name
        assert "Listening," not in text, path.name
