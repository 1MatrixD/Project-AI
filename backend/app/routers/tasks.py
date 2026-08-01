from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_project
from ..jobs_runner import runner
from ..models import Project, TaskItem, WorkLogEntry, utcnow
from ..schemas import (
    TaskCreateIn,
    TaskDoneIn,
    TaskOut,
    TaskUpdateIn,
    WorkLogIn,
    WorkLogOut,
)
from ..services import graphdb

router = APIRouter(prefix="/projects/{project_id}", tags=["tasks"])

VALID_STATUSES = {"planned", "in_progress", "review", "done", "cancelled"}


async def _next_order(session: AsyncSession, project_id: uuid.UUID, status: str) -> float:
    res = await session.execute(
        select(func.max(TaskItem.order)).where(
            TaskItem.project_id == project_id, TaskItem.status == status
        )
    )
    return (res.scalar() or 0.0) + 1.0


async def _get_task(session: AsyncSession, project: Project, task_id: uuid.UUID) -> TaskItem:
    task = await session.get(TaskItem, task_id)
    if task is None or task.project_id != project.id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


async def _sync_task_node(project: Project, task: TaskItem, files: list[str] | None = None) -> None:
    try:
        await graphdb.upsert_task_node(str(project.id), str(task.id), task.title, task.status, files)
    except Exception:
        pass  # граф может быть недоступен — не валим API


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
) -> list[TaskOut]:
    q = select(TaskItem).where(TaskItem.project_id == project.id)
    if status:
        q = q.where(TaskItem.status == status)
    q = q.order_by(TaskItem.status, TaskItem.order, TaskItem.created_at)
    res = await session.execute(q)
    return [TaskOut.model_validate(t) for t in res.scalars()]


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    data: TaskCreateIn,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    task = TaskItem(
        project_id=project.id,
        title=data.title.strip(),
        description=data.description,
        source=data.source if data.source in ("manual", "chat", "meeting", "doc") else "manual",
        plan=[str(p)[:500] for p in data.plan[:30]],
        order=await _next_order(session, project.id, "planned"),
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    await _sync_task_node(project, task)
    return TaskOut.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdateIn,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    task = await _get_task(session, project, task_id)
    if data.title is not None:
        task.title = data.title.strip()[:300]
    if data.description is not None:
        task.description = data.description[:8000]
    if data.plan is not None:
        task.plan = [str(p)[:500] for p in data.plan[:30]]
    if data.status is not None:
        if data.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Статус: {', '.join(sorted(VALID_STATUSES))}")
        if data.status != task.status:
            task.status = data.status
            task.order = await _next_order(session, project.id, data.status)
            if data.status == "done" and task.done_at is None:
                task.done_at = utcnow()
    await session.commit()
    await session.refresh(task)
    await _sync_task_node(project, task)
    return TaskOut.model_validate(task)


@router.post("/tasks/reorder")
async def reorder_tasks(
    body: dict,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Полный порядок колонки после drag&drop: {status, ordered_ids: [...]}"""
    status = body.get("status")
    ids = body.get("ordered_ids") or []
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Неверный статус")
    for pos, tid in enumerate(ids, start=1):
        task = await session.get(TaskItem, uuid.UUID(str(tid)))
        if task is None or task.project_id != project.id:
            continue
        task.status = status
        task.order = float(pos)
        if status == "done" and task.done_at is None:
            task.done_at = utcnow()
    await session.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/done", response_model=TaskOut)
async def mark_done(
    task_id: uuid.UUID,
    data: TaskDoneIn,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    """Пометить выполненной с отчётом: создаёт worklog и запускает суб-агента
    обновления карты знаний."""
    task = await _get_task(session, project, task_id)
    task.status = "done"
    task.report = data.report[:8000]
    task.done_at = utcnow()
    task.order = await _next_order(session, project.id, "done")
    entry = WorkLogEntry(
        project_id=project.id,
        task_id=task.id,
        description=f"Задача «{task.title}»: {data.report}"[:8000],
        files=[str(f)[:500] for f in data.files[:100]],
    )
    session.add(entry)
    await session.commit()
    await session.refresh(task)
    await _sync_task_node(project, task, [str(f) for f in data.files[:30]])
    if not await runner.has_active(project.id, ["index", "knowledge_update"]):
        await runner.submit(project.id, "knowledge_update", {})
    return TaskOut.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> None:
    task = await _get_task(session, project, task_id)
    await session.delete(task)
    await session.commit()


@router.post("/tasks/verify")
async def verify_tasks_endpoint(project: Project = Depends(get_project)) -> dict:
    """ИИ-проверка: какие открытые задачи уже реализованы в коде."""
    if await runner.has_active(project.id, ["verify_tasks"]):
        raise HTTPException(status_code=409, detail="Проверка уже идёт")
    job = await runner.submit(project.id, "verify_tasks", {})
    return {"job_id": str(job.id)}


# --- worklog ---

@router.get("/worklog", response_model=list[WorkLogOut])
async def list_worklog(
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> list[WorkLogOut]:
    res = await session.execute(
        select(WorkLogEntry)
        .where(WorkLogEntry.project_id == project.id)
        .order_by(desc(WorkLogEntry.created_at))
        .limit(100)
    )
    return [WorkLogOut.model_validate(w) for w in res.scalars()]


@router.post("/worklog", response_model=WorkLogOut, status_code=201)
async def add_worklog(
    data: WorkLogIn,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> WorkLogOut:
    if data.task_id is not None:
        await _get_task(session, project, data.task_id)
    entry = WorkLogEntry(
        project_id=project.id,
        task_id=data.task_id,
        description=data.description[:8000],
        files=[str(f)[:500] for f in data.files[:100]],
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    if not await runner.has_active(project.id, ["index", "knowledge_update"]):
        await runner.submit(project.id, "knowledge_update", {})
    return WorkLogOut.model_validate(entry)
