"""Eval targets: one agent run per dataset example.

No quota row. Calls the same agent factories as the app. Seed examples have no
learner database, so context tools see `_EvalSession` instead of `db=None`.
The prompts assembled from the dataset stay the user text.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.profile import Profile
from app.schemas.chat import TurnTiming
from app.services.agents.curriculum import TASK as CURRICULUM_TASK
from app.services.agents.curriculum import curriculum_agent
from app.services.agents.factory import CoachAgent
from app.services.agents.lesson_chat import lesson_agent
from app.services.agents.onboarding import onboarding_agent
from app.services.agents.report import TASK as REPORT_TASK
from app.services.agents.report import report_agent
from app.services.agents.runner import LLMError, invoke_agent, run_config
from app.services.agents.tools import AgentContext
from app.services.prompt_assembly import generation_user_prompt, lesson_context_block, report_user_prompt

# Stable ids for trace metadata. Evals do not read or write a user row.
_EVAL_USER = uuid.UUID(int=0)
_EVAL_LESSON = uuid.UUID(int=1)


class _EvalResult:
    """The slice of a SQLAlchemy result the context tools actually use."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _EvalResult:
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        if len(self._rows) > 1:
            raise RuntimeError("eval session returned more than one row")
        return self._rows[0] if self._rows else None


class _EvalSession:
    """Empty learner state, plus the profile and lesson the tools require to return.

    Curriculum calls `target_minutes`, which raises without a profile. Report tools
    raise without a lesson. This is the test seam: it is not a second pedagogy path.
    """

    def __init__(self) -> None:
        self.profile = SimpleNamespace(
            native_language="ru",
            target_language="en",
            goal_outcome="Travel",
            target_level="A2",
            level_strengths=None,
            level_weaknesses=None,
            time_budget={"minutes_per_session": 15},
            focus=None,
            constraints=None,
            grammar_mastery=None,
            vocabulary_summary=None,
        )
        self.lesson = SimpleNamespace(
            id=_EVAL_LESSON,
            lesson_number=1,
            payload={"session_summary": {}},
            accomplished_at=None,
            pace_status=None,
        )

    async def execute(self, statement: object, *_args: object, **_kwargs: object) -> _EvalResult:
        descriptions = getattr(statement, "column_descriptions", None) or []
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Profile:
            return _EvalResult([self.profile])
        return _EvalResult([])

    async def get(self, model: type, ident: object) -> object | None:
        if model is Lesson and ident == _EVAL_LESSON:
            return self.lesson
        return None


_EVAL_DB = _EvalSession()


def _history_text(inputs: dict[str, Any]) -> str:
    return "\n".join(f"{turn['role']}: {turn['text']}" for turn in inputs.get("history", []))


def _context(inputs: dict[str, Any], *, call_type: str, onboarding: bool) -> AgentContext:
    return AgentContext(
        user_id=_EVAL_USER,
        db=cast(AsyncSession, _EVAL_DB),
        call_type=call_type,
        native_language=inputs.get("native"),
        target_language=inputs.get("target"),
        onboarding=onboarding,
        lesson_id=_EVAL_LESSON if call_type == "report" else None,
        session_summary=inputs.get("session_summary"),
    )


async def _call(agent: CoachAgent, user_text: str, context: AgentContext) -> dict[str, Any]:
    try:
        parsed = await invoke_agent(
            agent,
            user_text=user_text,
            context=context,
            config=run_config(
                call_type=agent.call_type,
                model_id=agent.model_id,
                user_id=_EVAL_USER,
                thread_id=None,
                trace_metadata={"eval": True},
            ),
        )
    except LLMError as exc:
        return {"parsed": None, "error": exc.code}
    return {"parsed": parsed.model_dump(mode="json"), "error": None}


async def onboarding_turn(inputs: dict[str, Any]) -> dict[str, Any]:
    text = _history_text(inputs) or "Begin the interview."
    return await _call(onboarding_agent(None), text, _context(inputs, call_type="chat", onboarding=True))


async def lesson_turn(inputs: dict[str, Any]) -> dict[str, Any]:
    mistakes = "\n".join(f"  - {item['pattern_type']}: {item['example_text']}" for item in inputs.get("mistakes", []))
    timing = TurnTiming(active_minutes=inputs["active_minutes"], target_minutes=inputs["target_minutes"])
    block = lesson_context_block(inputs["curriculum"], None, mistakes or "  (none)", timing)
    history = _history_text(inputs)
    text = f"{block}\n\n{history}" if history else block
    return await _call(lesson_agent(None), text, _context(inputs, call_type="chat", onboarding=False))


async def curriculum(inputs: dict[str, Any]) -> dict[str, Any]:
    prompt = generation_user_prompt(inputs["context"])
    return await _call(
        curriculum_agent(),
        f"{CURRICULUM_TASK}\n\n{prompt}",
        _context(inputs, call_type="lesson_json", onboarding=False),
    )


async def report_patch(inputs: dict[str, Any]) -> dict[str, Any]:
    prompt = report_user_prompt(
        lesson_number=inputs["lesson_number"],
        finished_on=date.fromisoformat(inputs["finished_on"]),
        session_summary=inputs["session_summary"],
        mistakes=inputs.get("mistakes", []),
        pace_status=inputs.get("pace_status"),
        reports=inputs["reports"],
    )
    return await _call(
        report_agent(),
        f"{REPORT_TASK}\n\n{prompt}",
        _context(inputs, call_type="report", onboarding=False),
    )


TARGETS: dict[str, Any] = {
    "onboarding_turns": onboarding_turn,
    "lesson_turns": lesson_turn,
    "curriculum_gen": curriculum,
    "report_patch": report_patch,
}
