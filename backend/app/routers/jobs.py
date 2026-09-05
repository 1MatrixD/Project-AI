from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_project
from .. import i18n
from ..jobs_runner import runner
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


@router.get("/events")
async def job_events(
    request: Request, project: Project = Depends(get_project), lifetime: float | None = None
) -> StreamingResponse:
    """SSE-поток событий проекта: изменения фоновых задач и канбана.

    События: {"type": "job", "job": {...}} | {"type": "tasks_changed"} | {"type": "ping"}.
    Поток закрывается через `lifetime` секунд (по умолчанию 15 минут) —
    клиент переподключается сам.
    """
    project_id = project.id
    deadline = asyncio.get_event_loop().time() + max(1.0, min(lifetime or 900.0, 3600.0))

    async def gen():
        q = runner.subscribe(project_id)
        try:
            yield 'data: {"type": "hello"}\n\n'
            while True:
                timeout = min(15.0, deadline - asyncio.get_event_loop().time())
                if timeout <= 0:
                    return
                try:
                    event = await asyncio.wait_for(q.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    event = {"type": "ping"}
                if await request.is_disconnected():
                    return
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        finally:
            runner.unsubscribe(project_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None or job.project_id != project.id:
        raise HTTPException(status_code=404, detail=i18n._("Фоновая задача не найдена"))
    return JobOut.model_validate(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Отмена фоновой задачи: queued — сразу, running — после текущего батча."""
    job = await session.get(Job, job_id)
    if job is None or job.project_id != project.id:
        raise HTTPException(status_code=404, detail=i18n._("Фоновая задача не найдена"))
    result = await runner.cancel(job_id)
    if result is None:
        raise HTTPException(status_code=409, detail=i18n._("Фоновая задача уже завершена"))
    return {"status": result}
