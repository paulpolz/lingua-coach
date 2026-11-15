"""Report patch agent. One-shot invoke, no checkpointer."""

from __future__ import annotations

from app.config import settings
from app.schemas.llm import ReportPatch
from app.services.agents.factory import CoachAgent, build_agent
from app.services.agents.tools import REPORT_TOOLS

SYSTEM_PROMPT = "You patch the learner's reports. Call the tools for this turn before answering. Return the patch only."
TASK = "Patch the reports for the lesson that just finished."


def report_agent() -> CoachAgent:
    return build_agent(
        "report",
        settings.llm_model_lesson,
        REPORT_TOOLS,
        SYSTEM_PROMPT,
        ReportPatch,
        None,
    )
