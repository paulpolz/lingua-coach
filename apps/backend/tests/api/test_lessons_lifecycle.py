"""Lesson start / stop / finish through the HTTP API."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LessonStatus
from tests.factories import make_lesson, make_profile, make_user


async def test_fresh_generating_lesson_blocks_start(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    await make_profile(db, user)
    lesson = await make_lesson(db, user, status=LessonStatus.generating, payload={})

    response = await client.post("/api/v1/lessons/start")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "An active or generating lesson already exists",
        "code": "ACTIVE_LESSON_EXISTS",
        "active_lesson_id": str(lesson.id),
    }
