"""Best-effort structured-data extraction from onboarding chat replies.

Parses the fenced JSON marker blocks the model is instructed to emit (see
`ONBOARDING_EXTRACTION_CONTRACT` in app/services/skills.py) and validates them
with Pydantic. Chat streaming must never block on this — callers treat a
`None` result as "not ready yet", not an error.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.schemas.chat import LessonPlan, LessonTurnExtraction, TaskUpdate
from app.schemas.learner_profile import LearnerProfile
from app.schemas.roadmap import CourseRoadmap

_LEARNER_PROFILE_BLOCK = re.compile(r"```json:learner_profile\s*\n(.*?)```", re.DOTALL)
_COURSE_ROADMAP_BLOCK = re.compile(r"```json:course_roadmap\s*\n(.*?)```", re.DOTALL)
_LESSON_TURN_BLOCK = re.compile(r"```json:lesson_turn\s*\n(.*?)```", re.DOTALL)
_LESSON_PLAN_BLOCK = re.compile(r"```json:lesson_plan\s*\n(.*?)```", re.DOTALL)
_TASK_UPDATE_BLOCK = re.compile(r"```json:task_update\s*\n(.*?)```", re.DOTALL)
_REPORT_OPS_BLOCK = re.compile(r"```json:report_ops\s*\n(.*?)```", re.DOTALL)


def extract_learner_profile(text: str) -> LearnerProfile | None:
    """Return the last valid `learner_profile` block in `text`, if any."""
    matches = _LEARNER_PROFILE_BLOCK.findall(text)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
            return LearnerProfile.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def extract_course_roadmap(text: str) -> CourseRoadmap | None:
    """Return the last valid `course_roadmap` block in `text`, if any."""
    matches = _COURSE_ROADMAP_BLOCK.findall(text)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
            return CourseRoadmap.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def extract_lesson_turn(text: str) -> LessonTurnExtraction | None:
    """Return the last valid `lesson_turn` block in `text`, if any.

    Callers treat `None` the same as an all-empty/default extraction (no
    corrections/tips/mistakes, no plan update, `suggest_finish=False`) —
    the model is instructed to always emit this block (see
    `LESSON_EXTRACTION_CONTRACT`), but chat streaming must never block on a
    malformed one.
    """
    matches = _LESSON_TURN_BLOCK.findall(text)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
            return LessonTurnExtraction.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def extract_lesson_plan(text: str) -> LessonPlan | None:
    """Return the last valid `lesson_plan` block in `text`, if any."""
    matches = _LESSON_PLAN_BLOCK.findall(text)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
            return LessonPlan.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def extract_task_update(text: str) -> TaskUpdate | None:
    """Return the last valid `task_update` block in `text`, if any."""
    matches = _TASK_UPDATE_BLOCK.findall(text)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
            return TaskUpdate.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def extract_report_ops_json(text: str) -> dict | None:
    """Return the last parseable `report_ops` JSON object, or the whole text
    if it is already a JSON object (JSON-mode completions)."""
    matches = _REPORT_OPS_BLOCK.findall(text)
    candidates = list(reversed(matches))
    stripped = text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    for raw in candidates:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def strip_structured_blocks(text: str) -> str:
    """Remove the backend-only JSON marker blocks, keeping the conversational
    reply (including any markdown roadmap presentation) intact for display
    and persistence."""
    text = _LEARNER_PROFILE_BLOCK.sub("", text)
    text = _COURSE_ROADMAP_BLOCK.sub("", text)
    text = _LESSON_TURN_BLOCK.sub("", text)
    text = _LESSON_PLAN_BLOCK.sub("", text)
    text = _TASK_UPDATE_BLOCK.sub("", text)
    text = _REPORT_OPS_BLOCK.sub("", text)
    return text.strip()
