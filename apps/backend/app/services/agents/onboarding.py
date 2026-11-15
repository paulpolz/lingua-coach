"""Onboarding chat agent. Skills stay in tools, not in the system prompt."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.schemas.llm import OnboardingReply
from app.services.agents.factory import CoachAgent, build_agent
from app.services.agents.tools import ONBOARDING_TOOLS

SYSTEM_PROMPT = (
    "You are the onboarding coach. Call the tools for this turn before answering. Then send one learner-facing turn."
)


def onboarding_agent(checkpointer: Any) -> CoachAgent:
    return build_agent(
        "chat",
        settings.llm_model_chat,
        ONBOARDING_TOOLS,
        SYSTEM_PROMPT,
        OnboardingReply,
        checkpointer,
    )
