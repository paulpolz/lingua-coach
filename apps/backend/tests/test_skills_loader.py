"""Skill loader reads the real repo-root skills/*.md files without error."""

from __future__ import annotations

import pytest

from app.services import skills


def test_onboarding_mode_concatenates_interviewer_and_composer() -> None:
    text = skills.get_system_instruction("onboarding")
    assert "Onboarding Interviewer" in text
    assert "Course Composer" in text
    # Concatenation order per ai-api.md's orchestration table.
    assert text.index("Onboarding Interviewer") < text.index("Course Composer")


def test_lesson_mode_loads_exercise_tutor_only_by_default() -> None:
    text = skills.get_system_instruction("lesson")
    assert "Exercise Tutor" in text or "exercise_tutor" in text.lower()
    assert "Vocabulary Practice Formats" not in text


def test_lesson_mode_includes_vocab_formats_when_selected() -> None:
    text = skills.get_system_instruction("lesson", include_vocab_formats=True)
    assert "Vocabulary Practice Formats" in text
    assert text.index("Exercise Tutor") < text.index("Vocabulary Practice Formats")


def test_should_include_vocab_formats_ignores_daily_vocabulary_slots() -> None:
    assert skills.should_include_vocab_formats(None) is False
    assert skills.should_include_vocab_formats({"slots": []}) is False
    assert (
        skills.should_include_vocab_formats(
            {
                "slots": [
                    {"id": "warmup", "label": "Warm-up", "exercise_set": "..."},
                    {"id": "vocabulary", "label": "Vocabulary", "exercise_set": "6-10 items"},
                    {"id": "review", "label": "Review & log", "exercise_set": "..."},
                ]
            }
        )
        is False
    )
    assert (
        skills.should_include_vocab_formats(
            weekly_template={
                "activities": [
                    {"id": "vocabulary", "label": "Vocabulary", "minutes": 7},
                    {"id": "review", "label": "Review & log", "minutes": 2},
                ]
            }
        )
        is False
    )


def test_should_include_vocab_formats_detects_review_slots_and_template() -> None:
    assert (
        skills.should_include_vocab_formats(
            {"slots": [{"id": "vocab_review", "label": "Week-end drills", "exercise_set": "..."}]}
        )
        is True
    )
    assert (
        skills.should_include_vocab_formats(
            {"slots": [{"id": "production", "label": "Weekend vocab review", "exercise_set": "..."}]}
        )
        is True
    )
    assert (
        skills.should_include_vocab_formats(
            weekly_template={"activities": [{"id": "week_end_vocab", "label": "Format A", "minutes": 20}]}
        )
        is True
    )


def test_unknown_mode_raises() -> None:
    with pytest.raises(skills.SkillLoadError):
        skills.get_system_instruction("not-a-real-mode")


def test_missing_skill_file_raises_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "skills_dir", str(tmp_path))
    skills.clear_cache()
    try:
        with pytest.raises(skills.SkillLoadError):
            skills.get_system_instruction("onboarding")
    finally:
        skills.clear_cache()
