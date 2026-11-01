"""Report writer against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LessonStatus, UserReportType
from app.models.user_report import UserReport
from app.schemas.llm import ReportOp, ReportPatch
from app.services.report_seed import blank_progress_markdown
from app.services.report_writer import _update
from tests.factories import make_lesson, make_user
from tests.fake_llm import FakeLLM
from tests.integration.test_llm_usage_limits import _events


async def test_report_writer_applies_ops_from_model(db: AsyncSession, fake_llm: FakeLLM) -> None:
    user = await make_user(db)
    lesson = await make_lesson(db, user, status=LessonStatus.accomplished)
    progress = UserReport(user_id=user.id, report_type=UserReportType.progress, body=blank_progress_markdown())
    db.add(progress)
    await db.flush()
    fake_llm.push(
        ReportPatch(
            ops=[
                ReportOp(
                    report_type="progress",
                    op="append_entry",
                    section_id="update_log",
                    markdown="Noted the cafe order.",
                )
            ]
        )
    )

    await _update(
        db,
        user=user,
        lesson=lesson,
        session_summary={"worked_on": "orders"},
        profile=None,
        now=datetime(2026, 10, 28, tzinfo=UTC),
    )

    assert fake_llm.calls[-1].schema is ReportPatch
    assert "Noted the cafe order." in progress.body
    assert "<!-- section:update_log -->" in progress.body
    assert (await _events(db))[0].status == "ok"
