"""After a lesson finishes, one Gemini JSON call patches the four markdown reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import UserReportType
from app.models.lesson import Lesson
from app.models.mistake import Mistake
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport
from app.services import gemini
from app.services.gemini import ChatTurn
from app.services.llm_usage import complete, estimate_input_tokens, reserve_gemini_call
from app.services.prompt_assembly import report_system_instruction
from app.services.report_ops import apply_report_op
from app.services.report_seed import blank_errors_log_markdown, blank_progress_markdown

logger = logging.getLogger(__name__)

_BLANK = {
    UserReportType.progress: blank_progress_markdown,
    UserReportType.errors_log: blank_errors_log_markdown,
}


async def update_reports_after_lesson(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    session_summary: dict,
    profile: Profile | None,
    now: datetime,
) -> None:
    """Never raises: finishing a lesson must succeed even if the report call fails."""
    try:
        await _update(db, user=user, lesson=lesson, session_summary=session_summary, profile=profile, now=now)
    except Exception:  # noqa: BLE001
        logger.warning("report_patch_failed", exc_info=True, extra={"lesson_id": str(lesson.id)})


async def _update(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    session_summary: dict,
    profile: Profile | None,
    now: datetime,
) -> None:
    rows = (await db.execute(select(UserReport).where(UserReport.user_id == user.id))).scalars().all()
    reports = {row.report_type: row for row in rows}
    for report_type, factory in _BLANK.items():
        if report_type not in reports:
            reports[report_type] = UserReport(user_id=user.id, report_type=report_type, body=factory())
            db.add(reports[report_type])

    mistakes = (await db.execute(select(Mistake).where(Mistake.lesson_id == lesson.id))).scalars().all()
    native = profile.native_language if profile else None
    target = profile.target_language if profile else None
    prompt = (
        f"Lesson {lesson.lesson_number} finished on {now.date().isoformat()}.\n\n"
        f"Session summary: {json.dumps(session_summary, ensure_ascii=False)}\n\n"
        "Mistakes this lesson: "
        + json.dumps(
            [{"pattern_type": m.pattern_type, "example_text": m.example_text, "correction": m.correction,
              "occurrence_count": m.occurrence_count} for m in mistakes],
            ensure_ascii=False,
        )
        + f"\n\nPace status: {lesson.pace_status.value if lesson.pace_status else None}\n\n"
        f"Current reports: {json.dumps({t.value: r.body for t, r in reports.items()}, ensure_ascii=False)}\n\n"
        "Emit incremental ops only."
    )
    system_instruction = report_system_instruction(native, target)

    event = await reserve_gemini_call(
        db, user.id, "report", estimated_input_tokens=estimate_input_tokens(system_instruction, prompt)
    )
    tokens = event.input_tokens

    async def on_usage(count: int) -> None:
        nonlocal tokens
        tokens = count

    try:
        raw = await gemini.generate_json(
            system_instruction=system_instruction,
            history=[ChatTurn(role="user", text=prompt)],
            on_usage=on_usage,
            call_type="report",
        )
    except Exception:
        await complete(db, event, input_tokens=tokens, status="error", model=settings.gemini_model_lesson)
        raise
    await complete(db, event, input_tokens=tokens, status="ok", model=settings.gemini_model_lesson)

    for op in json.loads(raw).get("ops") or []:
        try:
            row = reports.get(UserReportType(op.get("report_type")))
        except ValueError:
            continue
        if row is not None:
            row.body = apply_report_op(row.body, op)
