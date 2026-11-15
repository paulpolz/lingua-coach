"""Skill and SQL context tools. Not retrievers: they call the existing readers."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import LearningPlanStatus, UserReportType
from app.models.learning_plan import LearningPlan
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.user_report import UserReport
from app.schemas.chat import TurnTiming
from app.services.lesson_timing import active_minutes, lesson_target_minutes
from app.services.memory import CHAT_MISTAKES, GENERATION_MISTAKES, rank_mistakes
from app.services.prompt_assembly import (
    generation_user_prompt,
    language_policy,
    learner_memory,
    lesson_context_block,
    log_context_tokens,
    mistake_lines,
    report_user_prompt,
)
from app.services.queries import get_profile
from app.services.report_seed import blank_errors_log_markdown, blank_progress_markdown
from app.services.skills import load_skill

_BLANK_REPORTS = {
    UserReportType.progress: blank_progress_markdown,
    UserReportType.errors_log: blank_errors_log_markdown,
}


@dataclass
class AgentContext:
    """Ids the HTTP layer or job already authorized. Tools must not take ids from the model."""

    user_id: uuid.UUID
    db: AsyncSession
    call_type: str
    native_language: str | None = None
    target_language: str | None = None
    onboarding: bool = False
    session_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    lesson_number: int | None = None
    session_summary: dict | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class ContextTool:
    tool: BaseTool
    run: Callable[[AgentContext], Awaitable[str]]

    @property
    def name(self) -> str:
        return self.tool.name


def context_tool(fn: Callable[[AgentContext], Awaitable[str]]) -> ContextTool:
    """Wrap a context reader as a tool. `runtime` is injected and hidden from the model."""
    description = fn.__doc__ or fn.__name__

    async def bound(runtime: ToolRuntime[AgentContext]) -> str:
        return await fn(runtime.context)

    bound.__name__ = fn.__name__.removeprefix("_")
    bound.__doc__ = description
    return ContextTool(tool(bound), fn)


async def _load_onboarding_interviewer(_ctx: AgentContext) -> str:
    """Load the onboarding interviewer instructions. Call before the first question."""
    return load_skill("onboarding_interviewer")


async def _load_course_composer(_ctx: AgentContext) -> str:
    """Load the course composer instructions. Call before drafting or revising a roadmap."""
    return load_skill("course_composer")


async def _load_exercise_tutor(_ctx: AgentContext) -> str:
    """Load the exercise tutor instructions. Call before teaching or generating a lesson."""
    return load_skill("exercise_tutor")


async def _load_report_writer(_ctx: AgentContext) -> str:
    """Load the report writer instructions. Call before patching reports."""
    return load_skill("report_writer")


async def _language_policy(ctx: AgentContext) -> str:
    """Return the language policy for this learner. Call before answering."""
    return language_policy(ctx.native_language, ctx.target_language, onboarding=ctx.onboarding)


async def _open_mistakes(db: AsyncSession, user_id: uuid.UUID) -> list[Mistake]:
    rows = await db.execute(select(Mistake).where(Mistake.user_id == user_id, Mistake.resolved_at.is_(None)))
    return list(rows.scalars().all())


async def _lesson_focus(ctx: AgentContext) -> str:
    if ctx.lesson_id is None:
        return ""
    lesson = await ctx.db.get(Lesson, ctx.lesson_id)
    curriculum = ((lesson.payload or {}).get("curriculum") if lesson else None) or {}
    return f"{curriculum.get('grammar_focus') or ''} {curriculum.get('vocab_theme') or ''}".strip()


async def _plan_focus(ctx: AgentContext) -> str:
    from app.services.lesson_generation import plan_focus

    plan = (
        (
            await ctx.db.execute(
                select(LearningPlan)
                .where(LearningPlan.user_id == ctx.user_id, LearningPlan.status == LearningPlanStatus.accepted)
                .order_by(LearningPlan.accepted_at.desc())
            )
        )
        .scalars()
        .first()
    )
    return plan_focus(plan)


async def _fetch_ranked_mistakes(ctx: AgentContext) -> str:
    """Return this learner's ranked open mistakes. Call before teaching or generating a lesson."""
    now = datetime.now(UTC)
    if ctx.call_type == "lesson_json":
        focus = await _plan_focus(ctx)
        limit = GENERATION_MISTAKES
    else:
        focus = await _lesson_focus(ctx)
        limit = CHAT_MISTAKES
    lines = mistake_lines(rank_mistakes(await _open_mistakes(ctx.db, ctx.user_id), focus, now, k=limit), now)
    log_context_tokens(ctx.call_type, {"mistakes": lines})
    return learner_memory(lines)


async def _fetch_lesson_curriculum_and_profile(ctx: AgentContext) -> str:
    """Return the current lesson curriculum, profile, and clock. Call before teaching."""
    lesson = await ctx.db.get(Lesson, ctx.lesson_id) if ctx.lesson_id is not None else None
    profile = await get_profile(ctx.db, ctx.user_id)
    curriculum = ((lesson.payload or {}).get("curriculum") if lesson else None) or {}
    now = datetime.now(UTC)
    focus = f"{curriculum.get('grammar_focus') or ''} {curriculum.get('vocab_theme') or ''}"
    lines = mistake_lines(rank_mistakes(await _open_mistakes(ctx.db, ctx.user_id), focus, now, k=CHAT_MISTAKES), now)
    timing = None
    if lesson is not None and ctx.session_id is not None:
        target = lesson_target_minutes(lesson, profile)
        if target is not None:
            active = await active_minutes(ctx.db, ctx.session_id, settings.lesson_idle_cap_minutes, until=now)
            timing = TurnTiming(active_minutes=active, target_minutes=target)
    log_context_tokens(
        ctx.call_type,
        {"curriculum": json.dumps(curriculum, ensure_ascii=False), "mistakes": lines},
    )
    return lesson_context_block(curriculum, profile, lines, timing)


async def _fetch_generation_context(ctx: AgentContext) -> str:
    """Return the roadmap, recent lessons, and mistakes for the next curriculum. Call before generating."""
    from app.services.lesson_generation import build_generation_context

    context = await build_generation_context(ctx.db, user_id=ctx.user_id, lesson_number=ctx.lesson_number or 1)
    log_context_tokens(ctx.call_type, {key: json.dumps(value, default=str) for key, value in context.items()})
    return generation_user_prompt(context)


async def _fetch_report_context(ctx: AgentContext) -> str:
    """Return the session summary, this lesson's mistakes, and the report tails. Call before patching."""
    if ctx.lesson_id is None:
        raise RuntimeError("report context requires a lesson")
    lesson = await ctx.db.get(Lesson, ctx.lesson_id)
    if lesson is None:
        raise RuntimeError("report context requires a lesson")
    rows = (await ctx.db.execute(select(UserReport).where(UserReport.user_id == ctx.user_id))).scalars().all()
    bodies = {kind.value: factory() for kind, factory in _BLANK_REPORTS.items()}
    bodies.update({row.report_type.value: row.body for row in rows})
    mistakes = (await ctx.db.execute(select(Mistake).where(Mistake.lesson_id == lesson.id))).scalars().all()
    summary = ctx.session_summary
    if summary is None:
        summary = (lesson.payload or {}).get("session_summary") or {}
    finished = ctx.finished_at or lesson.accomplished_at or datetime.now(UTC)
    return report_user_prompt(
        lesson_number=lesson.lesson_number,
        finished_on=finished.date(),
        session_summary=summary,
        mistakes=[
            {
                "pattern_type": item.pattern_type,
                "example_text": item.example_text,
                "correction": item.correction,
                "occurrence_count": item.occurrence_count,
            }
            for item in mistakes
        ],
        pace_status=lesson.pace_status.value if lesson.pace_status else None,
        reports=bodies,
    )


load_onboarding_interviewer = context_tool(_load_onboarding_interviewer)
load_course_composer = context_tool(_load_course_composer)
load_exercise_tutor = context_tool(_load_exercise_tutor)
load_report_writer = context_tool(_load_report_writer)
language_policy_tool = context_tool(_language_policy)
fetch_ranked_mistakes = context_tool(_fetch_ranked_mistakes)
fetch_lesson_curriculum_and_profile = context_tool(_fetch_lesson_curriculum_and_profile)
fetch_generation_context = context_tool(_fetch_generation_context)
fetch_report_context = context_tool(_fetch_report_context)

ONBOARDING_TOOLS = (load_onboarding_interviewer, load_course_composer, language_policy_tool)
LESSON_CHAT_TOOLS = (
    load_exercise_tutor,
    language_policy_tool,
    fetch_lesson_curriculum_and_profile,
    fetch_ranked_mistakes,
)
CURRICULUM_TOOLS = (load_exercise_tutor, language_policy_tool, fetch_ranked_mistakes, fetch_generation_context)
REPORT_TOOLS = (load_report_writer, language_policy_tool, fetch_report_context)
