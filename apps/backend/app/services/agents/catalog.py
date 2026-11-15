"""The four coach agents. Each one is a prompt, a tool list, a schema, and a checkpointer."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.schemas.llm import LessonCurriculum, LessonReply, OnboardingReply, ReportPatch
from app.services.agents.factory import CoachAgent, build_agent
from app.services.agents.tools import CURRICULUM_TOOLS, LESSON_CHAT_TOOLS, ONBOARDING_TOOLS, REPORT_TOOLS

ONBOARDING_PROMPT = (
    "You are the onboarding coach. Call the tools for this turn before answering. Then send one learner-facing turn."
)
LESSON_PROMPT = (
    "You are the lesson coach. Call the tools for this turn before answering. Then send one learner-facing turn."
)
CURRICULUM_PROMPT = (
    "You write one lesson curriculum. Call the tools for this turn before answering. Return the curriculum only."
)
REPORT_PROMPT = "You patch the learner's reports. Call the tools for this turn before answering. Return the patch only."

CURRICULUM_TASK = "Generate the next lesson curriculum."
REPORT_TASK = "Patch the reports for the lesson that just finished."


def onboarding_agent(checkpointer: Any) -> CoachAgent:
    return build_agent(
        "chat",
        settings.llm_model_chat,
        ONBOARDING_TOOLS,
        ONBOARDING_PROMPT,
        OnboardingReply,
        checkpointer,
    )


def lesson_agent(checkpointer: Any) -> CoachAgent:
    return build_agent(
        "chat",
        settings.llm_model_chat,
        LESSON_CHAT_TOOLS,
        LESSON_PROMPT,
        LessonReply,
        checkpointer,
    )


def curriculum_agent() -> CoachAgent:
    return build_agent(
        "lesson_json",
        settings.llm_model_lesson,
        CURRICULUM_TOOLS,
        CURRICULUM_PROMPT,
        LessonCurriculum,
        None,
    )


def report_agent() -> CoachAgent:
    return build_agent(
        "report",
        settings.llm_model_lesson,
        REPORT_TOOLS,
        REPORT_PROMPT,
        ReportPatch,
        None,
    )
