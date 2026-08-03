"""Pydantic validation for `LessonCurriculum` — docs/tech_requirements/database.md
"payload JSON shape" / skills/exercise_tutor.md "Lesson payload" (the
canonical nested shape, not readiness §8's flat example)."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.schemas.lesson import LessonCurriculum
from tests.fixtures import VALID_LESSON_CURRICULUM


def test_valid_curriculum_fixture_validates() -> None:
    curriculum = LessonCurriculum.model_validate(VALID_LESSON_CURRICULUM)
    assert curriculum.lesson_goal == VALID_LESSON_CURRICULUM["lesson_goal"]
    assert len(curriculum.slots) == 2
    assert curriculum.input_task.type == "listening"
    assert curriculum.partner_session is None


def test_curriculum_rejects_empty_slots() -> None:
    bad = copy.deepcopy(VALID_LESSON_CURRICULUM)
    bad["slots"] = []
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(bad)


def test_curriculum_rejects_empty_exit_criteria() -> None:
    bad = copy.deepcopy(VALID_LESSON_CURRICULUM)
    bad["exit_criteria"] = []
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(bad)


def test_curriculum_rejects_missing_required_field() -> None:
    bad = copy.deepcopy(VALID_LESSON_CURRICULUM)
    del bad["grammar_focus"]
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(bad)


def test_curriculum_rejects_invalid_input_task_type() -> None:
    bad = copy.deepcopy(VALID_LESSON_CURRICULUM)
    bad["input_task"]["type"] = "watching"  # only listening|reading are valid
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(bad)


def test_curriculum_rejects_negative_milestone_index() -> None:
    bad = copy.deepcopy(VALID_LESSON_CURRICULUM)
    bad["milestone_index"] = -1
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(bad)


def test_curriculum_rejects_malformed_slot_entry() -> None:
    bad = copy.deepcopy(VALID_LESSON_CURRICULUM)
    bad["slots"][0] = {"id": "warmup"}  # missing label/exercise_set
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(bad)
