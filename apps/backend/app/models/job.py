import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import JobStatus


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"), default=JobStatus.pending, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
