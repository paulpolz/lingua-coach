from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned
from app.db.session import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobResponse
from app.services.lesson_generation import reap_stale_generation

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    await reap_stale_generation(db, user.id)
    await db.commit()
    job = await get_owned(db, Job, job_id, user, "Job")

    return JobResponse(
        id=str(job.id),
        status=job.status.value,
        type=job.type,
        result_ref=job.result_ref,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
