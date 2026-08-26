"""Pydantic validation for the `course_roadmap` / `learner_profile` shapes,
and the chat-reply structured-block extraction util."""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from app.schemas.learner_profile import LearnerProfile
from app.schemas.roadmap import CourseRoadmap
from app.services import extraction
from tests.fixtures import VALID_COURSE_ROADMAP, VALID_LEARNER_PROFILE, VALID_LEARNER_PROFILE_ES


def test_valid_course_roadmap_fixture_validates() -> None:
    roadmap = CourseRoadmap.model_validate(VALID_COURSE_ROADMAP)
    assert roadmap.summary.target_plan_days == 90
    assert roadmap.summary.target_language == "en"
    assert roadmap.milestones[0].title == "Diagnostic & System Setup"


def test_course_roadmap_rejects_wrong_version() -> None:
    bad = copy.deepcopy(VALID_COURSE_ROADMAP)
    bad["version"] = 2
    with pytest.raises(ValidationError):
        CourseRoadmap.model_validate(bad)


def test_course_roadmap_rejects_missing_milestones() -> None:
    bad = copy.deepcopy(VALID_COURSE_ROADMAP)
    bad["milestones"] = []
    with pytest.raises(ValidationError):
        CourseRoadmap.model_validate(bad)


def test_course_roadmap_rejects_missing_required_field() -> None:
    bad = copy.deepcopy(VALID_COURSE_ROADMAP)
    del bad["summary"]["target_plan_days"]
    with pytest.raises(ValidationError):
        CourseRoadmap.model_validate(bad)


def test_valid_learner_profile_fixture_validates() -> None:
    profile = LearnerProfile.model_validate(VALID_LEARNER_PROFILE)
    assert profile.languages.native == "en"
    assert profile.languages.target == "en"
    assert profile.goal.outcome.startswith("Speak confidently")
    assert profile.focus.vocab_priorities == ["workplace phrasal verbs"]


def test_valid_learner_profile_es_fixture_validates() -> None:
    profile = LearnerProfile.model_validate(VALID_LEARNER_PROFILE_ES)
    assert profile.languages.native == "en"
    assert profile.languages.target == "es"


def test_learner_profile_requires_goal_outcome() -> None:
    bad = copy.deepcopy(VALID_LEARNER_PROFILE)
    del bad["goal"]["outcome"]
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(bad)


def _fenced(marker: str, payload: dict) -> str:
    return f"```json:{marker}\n{json.dumps(payload)}\n```"


def test_extract_learner_profile_from_reply_text() -> None:
    text = "Great, I have everything I need!\n\n" + _fenced("learner_profile", VALID_LEARNER_PROFILE)
    result = extraction.extract_learner_profile(text)
    assert result is not None
    assert result.goal.outcome == VALID_LEARNER_PROFILE["goal"]["outcome"]


def test_extract_course_roadmap_from_reply_text() -> None:
    text = "# Your roadmap\n...\n\n" + _fenced("course_roadmap", VALID_COURSE_ROADMAP)
    result = extraction.extract_course_roadmap(text)
    assert result is not None
    assert result.summary.target_plan_days == 90


def test_extract_returns_none_when_no_block_present() -> None:
    assert extraction.extract_learner_profile("just chatting, no JSON here") is None
    assert extraction.extract_course_roadmap("just chatting, no JSON here") is None


def test_extract_returns_none_on_malformed_json() -> None:
    text = "```json:learner_profile\n{not valid json\n```"
    assert extraction.extract_learner_profile(text) is None


def test_strip_structured_blocks_keeps_markdown_removes_json() -> None:
    text = (
        "Here is your roadmap in plain language.\n\n"
        + _fenced("course_roadmap", VALID_COURSE_ROADMAP)
        + "\n\nDoes this work for you?"
    )
    cleaned = extraction.strip_structured_blocks(text)
    assert "json:course_roadmap" not in cleaned
    assert "Here is your roadmap in plain language." in cleaned
    assert "Does this work for you?" in cleaned


def test_extract_lesson_plan_and_task_update() -> None:
    text = (
        "Today we will:\n\n"
        + _fenced("lesson_plan", {"tasks": [{"id": "warmup", "label": "Warm-up", "minutes": 5}]})
        + "\n"
        + _fenced("task_update", {"completed_task_ids": ["warmup"]})
    )
    plan = extraction.extract_lesson_plan(text)
    update = extraction.extract_task_update(text)
    assert plan is not None
    assert plan.tasks[0].id == "warmup"
    assert plan.tasks[0].minutes == 5
    assert update is not None
    assert update.completed_task_ids == ["warmup"]
    cleaned = extraction.strip_structured_blocks(text)
    assert "json:lesson_plan" not in cleaned
    assert "json:task_update" not in cleaned
    assert "Today we will:" in cleaned


def test_extract_report_ops_json_from_raw_object() -> None:
    raw = (
        '{"ops": [{"report_type": "progress", "op": "append_entry",'
        ' "section_id": "update_log", "markdown": "x"}]}'
    )
    data = extraction.extract_report_ops_json(raw)
    assert data is not None
    assert data["ops"][0]["section_id"] == "update_log"
