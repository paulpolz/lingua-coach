"""Skill loading."""

from __future__ import annotations

from app.services.skills import get_system_instruction


def test_lesson_instruction_is_the_exercise_tutor_only() -> None:
    text = get_system_instruction("lesson")
    assert text.startswith("# Exercise Tutor")


def test_onboarding_instruction_joins_interviewer_and_composer() -> None:
    text = get_system_instruction("onboarding")
    assert text.index("# Onboarding Interviewer") < text.index("# Course Composer")
