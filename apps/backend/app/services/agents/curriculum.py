"""Lesson curriculum agent. One-shot invoke, no checkpointer."""

from __future__ import annotations

from app.config import settings
from app.schemas.llm import LessonCurriculum
from app.services.agents.factory import CoachAgent, build_agent
from app.services.agents.tools import CURRICULUM_TOOLS

SYSTEM_PROMPT = (
    "You write one lesson curriculum. Call the tools for this turn before answering. Return the curriculum only."
)
TASK = "Generate the next lesson curriculum."


def curriculum_agent() -> CoachAgent:
    return build_agent(
        "lesson_json",
        settings.llm_model_lesson,
        CURRICULUM_TOOLS,
        SYSTEM_PROMPT,
        LessonCurriculum,
        None,
    )
