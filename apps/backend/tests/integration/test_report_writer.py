"""Report writer against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.enums import LessonStatus, UserReportType
from app.models.user_report import UserReport
from app.schemas.llm import ReportOp, ReportPatch
from app.services.report_ops import apply_report_op, wrap_section
from app.services.report_seed import blank_errors_log_markdown, blank_progress_markdown
from app.services.report_writer import _update
from tests.factories import make_lesson, make_user
from tests.fake_llm import FakeLLM, LLMCall
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


async def test_report_prompt_sends_log_tails_and_rejects_patching_a_log(db: AsyncSession, fake_llm: FakeLLM) -> None:
    user = await make_user(db)
    lesson = await make_lesson(db, user, status=LessonStatus.accomplished)
    history = "\n\n".join(f"- day {i}: old entry {i}" for i in range(1, 41))
    errors = UserReport(
        user_id=user.id,
        report_type=UserReportType.errors_log,
        body=blank_errors_log_markdown().replace(wrap_section("daily_log", ""), wrap_section("daily_log", history)),
    )
    db.add(errors)
    await db.flush()
    fake_llm.push(
        ReportPatch(
            ops=[
                ReportOp(report_type="errors_log", op="patch_section", section_id="daily_log", markdown="wiped"),
                ReportOp(report_type="errors_log", op="append_entry", section_id="daily_log", markdown="- day 41"),
            ]
        )
    )

    await _update(db, user=user, lesson=lesson, session_summary={}, profile=None, now=datetime(2026, 11, 1, tzinfo=UTC))

    prompt = fake_llm.calls[-1].text
    assert "(showing the last 5 of 40 entries)" in prompt
    assert "old entry 36" in prompt and "old entry 35\\n" not in prompt and "old entry 1\\n" not in prompt
    assert "wiped" not in errors.body
    assert "old entry 1\n" in errors.body and errors.body.rstrip().count("- day") == 41


async def test_report_written_meanwhile_is_not_overwritten(
    db: AsyncSession, fake_llm: FakeLLM, db_conn: AsyncConnection
) -> None:
    """Two finishes close together: the second update must not drop the first one's entry."""
    user = await make_user(db)
    lesson = await make_lesson(db, user, status=LessonStatus.accomplished)
    db.add(UserReport(user_id=user.id, report_type=UserReportType.progress, body=blank_progress_markdown()))
    await db.flush()
    user_id = user.id

    async def concurrent_update_lands(_call: LLMCall) -> ReportPatch:
        async with AsyncSession(bind=db_conn, join_transaction_mode="create_savepoint") as other:
            row = (
                await other.execute(
                    select(UserReport).where(
                        UserReport.user_id == user_id, UserReport.report_type == UserReportType.progress
                    )
                )
            ).scalar_one()
            row.body = apply_report_op(
                row.body, {"op": "append_entry", "section_id": "update_log", "markdown": "- from lesson A"}
            )
            await other.commit()
        return ReportPatch(
            ops=[
                ReportOp(report_type="progress", op="append_entry", section_id="update_log", markdown="- from lesson B")
            ]
        )

    fake_llm.push(concurrent_update_lands)

    await _update(db, user=user, lesson=lesson, session_summary={}, profile=None, now=datetime(2026, 11, 1, tzinfo=UTC))
    await db.flush()

    db.expire_all()
    body = (
        await db.execute(
            select(UserReport.body).where(
                UserReport.user_id == user_id, UserReport.report_type == UserReportType.progress
            )
        )
    ).scalar_one()
    assert "- from lesson A" in body and "- from lesson B" in body
