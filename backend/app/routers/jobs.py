from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_project
from ..models import Job, Project
from ..schemas import JobOut

router = APIRouter(prefix="/projects/{project_id}/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
async def list_jobs(
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
    limit: int = 20,
) -> list[JobOut]:
    res = await session.execute(
        select(Job)
        .where(Job.project_id == project.id)
        .order_by(desc(Job.created_at))
        .limit(min(limit, 100))
    )
    return [JobOut.model_validate(j) for j in res.scalars()]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None or job.project_id != project.id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return JobOut.model_validate(job)
