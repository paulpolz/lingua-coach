from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UserReportType


class UserReportOut(BaseModel):
    report_type: UserReportType
    body: str | None = None
    updated_at: datetime | None = None
