"""`GET /api/v1/jobs/{job_id}` — docs/implementation-readiness.md §6.

Not lesson-scoped (a `jobs` row only carries `type` + `result_ref`), so this
depends on plain `get_current_user` rather than the onboarding gate — the
lesson that spawned the job is already gated at `POST /lessons/start`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise APIError(404, "Job not found", "NOT_FOUND") from None

    job = await db.get(Job, job_uuid)
    if job is None or job.user_id != user.id:
        raise APIError(404, "Job not found", "NOT_FOUND")

    return JobResponse(
        id=str(job.id),
        status=job.status.value,
        type=job.type,
        result_ref=job.result_ref,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
