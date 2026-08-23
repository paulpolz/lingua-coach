from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import UserReportType

ReportOpKind = Literal["append_entry", "patch_section"]


class ReportOp(BaseModel):
    report_type: UserReportType
    op: ReportOpKind
    section_id: str
    markdown: str


class ReportOpsPayload(BaseModel):
    ops: list[ReportOp] = Field(default_factory=list)


class UserReportOut(BaseModel):
    report_type: UserReportType
    body: str | None = None
    updated_at: datetime | None = None
