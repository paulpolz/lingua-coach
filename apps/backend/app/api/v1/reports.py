"""`GET /api/v1/reports/{report_type}` — current user's markdown coach report."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarding_complete
from app.db.session import get_db
from app.models.enums import UserReportType
from app.models.user import User
from app.models.user_report import UserReport
from app.schemas.report import UserReportOut

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{report_type}", response_model=UserReportOut)
async def get_report(
    report_type: UserReportType,
    user: User = Depends(require_onboarding_complete),
    db: AsyncSession = Depends(get_db),
) -> UserReportOut:
    result = await db.execute(
        select(UserReport).where(
            UserReport.user_id == user.id, UserReport.report_type == report_type
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return UserReportOut(report_type=report_type, body=None, updated_at=None)
    return UserReportOut(
        report_type=row.report_type, body=row.body, updated_at=row.updated_at
    )
