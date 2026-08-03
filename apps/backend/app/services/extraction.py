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

from app.schemas.chat import LessonTurnExtraction
from app.schemas.learner_profile import LearnerProfile
from app.schemas.roadmap import CourseRoadmap

_LEARNER_PROFILE_BLOCK = re.compile(r"```json:learner_profile\s*\n(.*?)```", re.DOTALL)
_COURSE_ROADMAP_BLOCK = re.compile(r"```json:course_roadmap\s*\n(.*?)```", re.DOTALL)
_LESSON_TURN_BLOCK = re.compile(r"```json:lesson_turn\s*\n(.*?)```", re.DOTALL)


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


def strip_structured_blocks(text: str) -> str:
    """Remove the backend-only JSON marker blocks, keeping the conversational
    reply (including any markdown roadmap presentation) intact for display
    and persistence."""
    text = _LEARNER_PROFILE_BLOCK.sub("", text)
    text = _COURSE_ROADMAP_BLOCK.sub("", text)
    text = _LESSON_TURN_BLOCK.sub("", text)
    return text.strip()
