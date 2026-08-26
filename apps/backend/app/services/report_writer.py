"""Finish-time incremental updates to per-user markdown reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserReportType
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport
from app.schemas.lesson import SessionSummary
from app.schemas.report import ReportOp, ReportOpsPayload
from app.services.gemini import ChatTurn
from app.services.extraction import extract_report_ops_json
from app.services import gemini as gemini_service
from app.services.languages import language_policy_block
from app.services.report_ops import apply_report_ops
from app.services.report_seed import blank_errors_log_markdown, blank_progress_markdown
from app.services.skills import REPORT_PATCH_CONTRACT, load_skill

logger = logging.getLogger(__name__)

_TEMPLATES = {
    UserReportType.progress: blank_progress_markdown,
    UserReportType.errors_log: blank_errors_log_markdown,
}


async def _get_or_create_report(
    db: AsyncSession, user_id, report_type: UserReportType, factory
) -> UserReport:
    result = await db.execute(
        select(UserReport).where(
            UserReport.user_id == user_id, UserReport.report_type == report_type
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserReport(user_id=user_id, report_type=report_type, body=factory())
        db.add(row)
        await db.flush()
    return row


async def update_reports_after_lesson(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    session_summary: SessionSummary,
    profile: Profile | None,
    now: datetime,
) -> None:
    """Best-effort: one structured JSON call, then apply append/patch ops.

    Never raises — lesson finish must succeed even if report generation fails.
    """
    try:
        await _update_reports_after_lesson(
            db, user=user, lesson=lesson, session_summary=session_summary, profile=profile, now=now
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "report_patch_failed",
            exc_info=True,
            extra={"user_id": str(user.id), "lesson_id": str(lesson.id)},
        )


async def _update_reports_after_lesson(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    session_summary: SessionSummary,
    profile: Profile | None,
    now: datetime,
) -> None:
    progress = await _get_or_create_report(
        db, user.id, UserReportType.progress, blank_progress_markdown
    )
    errors_log = await _get_or_create_report(
        db, user.id, UserReportType.errors_log, blank_errors_log_markdown
    )
    roadmap = (
        await db.execute(
            select(UserReport).where(
                UserReport.user_id == user.id, UserReport.report_type == UserReportType.roadmap
            )
        )
    ).scalar_one_or_none()
    four_week = (
        await db.execute(
            select(UserReport).where(
                UserReport.user_id == user.id,
                UserReport.report_type == UserReportType.four_week_plan,
            )
        )
    ).scalar_one_or_none()

    mistakes_result = await db.execute(select(Mistake).where(Mistake.lesson_id == lesson.id))
    mistakes = [
        {
            "pattern_type": m.pattern_type,
            "example_text": m.example_text,
            "correction": m.correction,
            "occurrence_count": m.occurrence_count,
        }
        for m in mistakes_result.scalars().all()
    ]

    current_docs = {
        "progress": progress.body,
        "errors_log": errors_log.body,
        "roadmap": roadmap.body if roadmap else None,
        "four_week_plan": four_week.body if four_week else None,
    }
    pace_snapshot = {
        "target_plan_days": profile.target_plan_days if profile else None,
        "plan_slip_days": profile.plan_slip_days if profile else 0,
        "projected_completion_at": (
            profile.projected_completion_at.isoformat()
            if profile and profile.projected_completion_at
            else None
        ),
        "pace_status": lesson.pace_status.value if lesson.pace_status else None,
    }
    native = profile.native_language if profile else None
    target = profile.target_language if profile else None
    prompt = (
        f"Lesson {lesson.lesson_number} finished at {now.date().isoformat()}.\n\n"
        f"Native language: {native or '(not set)'}\n"
        f"Target language: {target or 'en'}\n\n"
        f"Session summary JSON:\n{session_summary.model_dump_json()}\n\n"
        f"Mistakes this lesson JSON:\n{json.dumps(mistakes)}\n\n"
        f"Pace snapshot JSON:\n{json.dumps(pace_snapshot)}\n\n"
        f"Current report markdown JSON:\n{json.dumps(current_docs)}\n\n"
        "Emit incremental ops only."
    )
    policy = language_policy_block(surface="report", native=native, target=target)
    system_instruction = f"{load_skill('report_writer')}\n\n{REPORT_PATCH_CONTRACT}\n\n{policy}"
    raw = await gemini_service.generate_json(
        system_instruction=system_instruction,
        history=[ChatTurn(role="user", text=prompt)],
        response_schema=ReportOpsPayload,
    )
    parsed = extract_report_ops_json(raw) or {}
    payload = ReportOpsPayload.model_validate(parsed)

    reports_by_type: dict[UserReportType, UserReport] = {
        UserReportType.progress: progress,
        UserReportType.errors_log: errors_log,
    }
    if roadmap is not None:
        reports_by_type[UserReportType.roadmap] = roadmap
    if four_week is not None:
        reports_by_type[UserReportType.four_week_plan] = four_week

    grouped: dict[UserReportType, list[ReportOp]] = {}
    for op in payload.ops:
        grouped.setdefault(op.report_type, []).append(op)

    for report_type, ops in grouped.items():
        row = reports_by_type.get(report_type)
        if row is None:
            continue
        row.body = apply_report_ops(row.body, ops)
