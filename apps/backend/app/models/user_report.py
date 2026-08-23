import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import UserReportType


class UserReport(Base, TimestampMixin):
    """Per-user markdown coach reports (progress, error log, roadmap, plan)."""

    __tablename__ = "user_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "report_type", name="uq_user_reports_user_id_report_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[UserReportType] = mapped_column(
        SAEnum(UserReportType, name="user_report_type"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
