"""Skill loading."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.services.skills import load_skill


def test_each_skill_file_loads() -> None:
    assert load_skill("exercise_tutor").startswith("# Exercise Tutor")
    assert "vocabulary_practice_formats" not in load_skill("exercise_tutor")
    assert load_skill("onboarding_interviewer").startswith("# Onboarding Interviewer")
    assert load_skill("course_composer").startswith("# Course Composer")
    assert load_skill("report_writer").startswith("# Report Writer")


def test_retired_skill_file_is_gone() -> None:
    assert not (Path(settings.skills_dir) / "vocabulary_practice_formats.md").exists()


def test_skills_never_mention_speaking_slots_or_listening_rows() -> None:
    for path in Path(settings.skills_dir).glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "partner_session" not in text, path.name
        assert "Listening," not in text, path.name
