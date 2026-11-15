"""After a lesson finishes, one structured Gemini call patches the four markdown reports."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.enums import UserReportType
from app.models.lesson import Lesson
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport
from app.services.agents.report import TASK, report_agent
from app.services.agents.runner import metered_agent_run
from app.services.agents.tools import AgentContext
from app.services.queries import get_profile
from app.services.report_ops import apply_report_op, is_log_section
from app.services.report_seed import blank_errors_log_markdown, blank_progress_markdown

logger = get_logger(__name__)

_BLANK = {
    UserReportType.progress: blank_progress_markdown,
    UserReportType.errors_log: blank_errors_log_markdown,
}


async def run_report_update(*, user_id: uuid.UUID, lesson_id: uuid.UUID, session_summary: dict) -> None:
    """Background task after finish has committed. Own session; never raises.

    A failed report call never undoes the finish; the reports just miss this lesson.
    """
    async with AsyncSessionLocal() as db:
        try:
            user = await db.get(User, user_id)
            lesson = await db.get(Lesson, lesson_id)
            if user is None or lesson is None:
                return
            profile = await get_profile(db, user_id)
            now = lesson.accomplished_at or datetime.now(UTC)
            await _update(db, user=user, lesson=lesson, session_summary=session_summary, profile=profile, now=now)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning(
                "report_patch_failed",
                exc_info=True,
                extra={"event": "report_patch_failed", "lesson_id": str(lesson_id)},
            )


async def _locked_reports(db: AsyncSession, user_id: uuid.UUID) -> dict[UserReportType, UserReport]:
    """The user's reports re-read after the LLM call and locked until commit.

    Two finishes close together run two background updates. Re-reading `FOR UPDATE` makes the
    second wait for the first commit and apply its ops to the fresh bodies instead of writing
    back the bodies it read before its LLM call. No lock is held during the call itself.
    """
    await db.execute(
        insert(UserReport)
        .values([{"user_id": user_id, "report_type": t, "body": factory()} for t, factory in _BLANK.items()])
        .on_conflict_do_nothing(index_elements=["user_id", "report_type"])
    )
    rows = (
        await db.execute(
            select(UserReport)
            .where(UserReport.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalars()
    return {row.report_type: row for row in rows}


async def _update(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    session_summary: dict,
    profile: Profile | None,
    now: datetime,
) -> None:
    patch = await metered_agent_run(
        db,
        user.id,
        "report",
        agent=report_agent(),
        user_text=TASK,
        context=AgentContext(
            user_id=user.id,
            db=db,
            call_type="report",
            native_language=profile.native_language if profile else None,
            target_language=profile.target_language if profile else None,
            lesson_id=lesson.id,
            lesson_number=lesson.lesson_number,
            session_summary=session_summary,
            finished_at=now,
        ),
        trace_metadata={"lesson_number": lesson.lesson_number},
    )
    reports = await _locked_reports(db, user.id)
    for op in patch.ops:
        if op.op == "patch_section" and is_log_section(op.report_type, op.section_id):
            # The model saw only the tail; a patch would replace the whole history with it.
            logger.warning(
                "report_op_rejected",
                extra={"event": "report_op_rejected", "report_type": op.report_type, "section_id": op.section_id},
            )
            continue
        row = reports.get(UserReportType(op.report_type))
        if row is not None:
            row.body = apply_report_op(row.body, op.model_dump())
