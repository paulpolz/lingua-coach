"""Eval targets: build the production prompt for one dataset example and make one LLM call.

No database and no quota rows: evals call `generate_structured` directly, with the same
system instructions and prompt builders the app uses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.config import settings
from app.schemas.chat import TurnTiming
from app.schemas.llm import LessonCurriculum, LessonReply, OnboardingReply, ReportPatch
from app.services.gemini import ChatTurn, GeminiError, generate_structured
from app.services.prompt_assembly import (
    generation_user_prompt,
    lesson_context_block,
    lesson_generation_system_instruction,
    lesson_system_instruction,
    onboarding_system_instruction,
    report_system_instruction,
    report_user_prompt,
)

Target = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _history(inputs: dict[str, Any]) -> list[ChatTurn]:
    return [ChatTurn(role=t["role"], text=t["text"]) for t in inputs.get("history", [])]


async def _call(
    schema: type[BaseModel], system: str, history: list[ChatTurn], call_type: str, model_id: str
) -> dict[str, Any]:
    try:
        parsed = await generate_structured(
            model_id=model_id,
            schema=schema,
            system_instruction=system,
            history=history,
            call_type=call_type,
            trace_metadata={"eval": True},
        )
    except GeminiError as exc:
        return {"parsed": None, "error": exc.code}
    return {"parsed": parsed.model_dump(mode="json"), "error": None}


async def onboarding_turn(inputs: dict[str, Any]) -> dict[str, Any]:
    system = onboarding_system_instruction(inputs.get("native"), inputs.get("target"))
    return await _call(OnboardingReply, system, _history(inputs), "chat", settings.gemini_model_chat)


async def lesson_turn(inputs: dict[str, Any]) -> dict[str, Any]:
    mistakes = "\n".join(f"  - {m['pattern_type']}: {m['example_text']}" for m in inputs.get("mistakes", []))
    timing = TurnTiming(active_minutes=inputs["active_minutes"], target_minutes=inputs["target_minutes"])
    context = lesson_context_block(inputs["curriculum"], None, mistakes or "  (none)", timing)
    system = lesson_system_instruction(inputs.get("native"), inputs["target"])
    history = [ChatTurn(role="user", text=context), *_history(inputs)]
    return await _call(LessonReply, system, history, "chat", settings.gemini_model_chat)


async def curriculum(inputs: dict[str, Any]) -> dict[str, Any]:
    system = lesson_generation_system_instruction(inputs.get("native"), inputs.get("target"))
    prompt = generation_user_prompt(inputs["context"])
    return await _call(
        LessonCurriculum, system, [ChatTurn(role="user", text=prompt)], "lesson_json", settings.gemini_model_lesson
    )


async def report_patch(inputs: dict[str, Any]) -> dict[str, Any]:
    system = report_system_instruction(inputs.get("native"), inputs.get("target"))
    prompt = report_user_prompt(
        lesson_number=inputs["lesson_number"],
        finished_on=date.fromisoformat(inputs["finished_on"]),
        session_summary=inputs["session_summary"],
        mistakes=inputs.get("mistakes", []),
        pace_status=inputs.get("pace_status"),
        reports=inputs["reports"],
    )
    return await _call(
        ReportPatch, system, [ChatTurn(role="user", text=prompt)], "report", settings.gemini_model_lesson
    )


TARGETS: dict[str, Target] = {
    "onboarding_turns": onboarding_turn,
    "lesson_turns": lesson_turn,
    "curriculum_gen": curriculum,
    "report_patch": report_patch,
}
