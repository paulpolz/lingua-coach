"""Lesson chat agent."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.schemas.llm import LessonReply
from app.services.agents.factory import CoachAgent, build_agent
from app.services.agents.tools import LESSON_CHAT_TOOLS

SYSTEM_PROMPT = (
    "You are the lesson coach. Call the tools for this turn before answering. Then send one learner-facing turn."
)


def lesson_agent(checkpointer: Any) -> CoachAgent:
    return build_agent(
        "chat",
        settings.llm_model_chat,
        LESSON_CHAT_TOOLS,
        SYSTEM_PROMPT,
        LessonReply,
        checkpointer,
    )
