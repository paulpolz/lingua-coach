import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clerk_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(default=False, nullable=False)
    plan_accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
