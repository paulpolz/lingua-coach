"""Small read queries shared by routers and services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import LessonStatus
from app.models.lesson import Lesson
from app.models.profile import Profile


def stale_generation_cutoff() -> datetime:
    """A `generating` lesson older than this lost its job (the job runs in the web process)."""
    return datetime.now(UTC) - timedelta(seconds=settings.llm_timeout_seconds * 2)


async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    return (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one_or_none()


async def active_lesson(db: AsyncSession, user_id: uuid.UUID) -> Lesson | None:
    """The active lesson, or a generating one that is not stale (see reap_stale_generation)."""
    return (
        await db.execute(
            select(Lesson).where(
                Lesson.user_id == user_id,
                or_(
                    Lesson.status == LessonStatus.active,
                    and_(Lesson.status == LessonStatus.generating, Lesson.created_at >= stale_generation_cutoff()),
                ),
            )
        )
    ).scalar_one_or_none()


async def accomplished_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    query = select(func.count()).select_from(Lesson)
    return await db.scalar(query.where(Lesson.user_id == user_id, Lesson.status == LessonStatus.accomplished)) or 0


async def last_accomplished(db: AsyncSession, user_id: uuid.UUID) -> Lesson | None:
    return (
        await db.execute(
            select(Lesson)
            .where(Lesson.user_id == user_id, Lesson.status == LessonStatus.accomplished)
            .order_by(Lesson.accomplished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
