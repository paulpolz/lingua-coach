"""LLM schema behavior: legacy JSON still reads, bounds and normalization hold."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.llm import (
    CourseRoadmap,
    LearnerProfile,
    LessonCurriculum,
    LessonReply,
    MistakeEntry,
    OnboardingReply,
    TimeBudget,
)
from tests.factories import roadmap_dict


def test_legacy_curriculum_keys_are_ignored_but_new_fields_are_required() -> None:
    with pytest.raises(ValidationError):
        LessonCurriculum.model_validate(
            {"lesson_goal": "x", "grammar_focus": "y", "vocab_theme": "z", "milestone_index": 0}
        )


def test_legacy_roadmap_activities_are_dropped() -> None:
    legacy = roadmap_dict(
        weekly_template={"minutes_per_session": 60, "activities": [{"id": "w", "label": "W", "minutes": 5}]}
    )
    dumped = CourseRoadmap.model_validate(legacy).model_dump()
    assert dumped["weekly_template"] == {"minutes_per_session": 60, "sessions_per_week": None, "weekends": None}


@pytest.mark.parametrize(("given", "stored"), [(3, None), (240, None), (0, None), (5, 5), (180, 180), (15, 15)])
def test_out_of_range_lesson_minutes_from_the_model_become_unknown(given: int, stored: int | None) -> None:
    # A rejected value would fail the whole turn (502) on every retry; None makes the interviewer ask again.
    assert TimeBudget(minutes_per_session=given).minutes_per_session == stored


def test_out_of_range_minutes_do_not_fail_a_reply() -> None:
    onboarding = OnboardingReply.model_validate(
        {
            "content": "ok",
            "learner_profile": {
                "languages": {"native": "ru", "target": "en"},
                "time_budget": {"minutes_per_session": 3},
            },
        }
    )
    lesson = LessonReply.model_validate(
        {"content": "ok", "plan_updates": {"time_budget": {"minutes_per_session": 240}}}
    )
    assert onboarding.learner_profile and onboarding.learner_profile.time_budget
    assert onboarding.learner_profile.time_budget.minutes_per_session is None
    assert lesson.plan_updates and lesson.plan_updates.time_budget
    assert lesson.plan_updates.time_budget.minutes_per_session is None


def test_mistake_pattern_labels_are_normalized() -> None:
    entry = MistakeEntry(pattern_type="  Missing   Articles ", example_text="x", correction="y")
    assert entry.pattern_type == "missing articles"


def test_legacy_profile_partner_fields_are_ignored() -> None:
    profile = LearnerProfile.model_validate(
        {
            "languages": {"native": " ru ", "target": "en "},
            "time_budget": {"minutes_per_session": 20, "optional_partner_minutes": 30},
            "constraints": {"practice_partner": {"available": True}},
        }
    )
    assert profile.languages.native == "ru" and profile.languages.target == "en"
    assert "optional_partner_minutes" not in profile.model_dump()["time_budget"]
    assert "practice_partner" not in profile.model_dump()["constraints"]


def test_reply_content_is_stripped_and_retired_keys_ignored() -> None:
    reply = LessonReply.model_validate({"content": "  hi ", "lesson_plan": {"tasks": []}, "completed_task_ids": ["a"]})
    assert reply.content == "hi"
    assert set(reply.model_dump()) == {
        "content",
        "corrections",
        "tips",
        "mistakes",
        "practiced",
        "suggest_finish",
        "plan_updates",
    }


def test_empty_content_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LessonReply(content="   ")
