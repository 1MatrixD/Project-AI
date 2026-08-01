from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_user, get_project
from ..jobs_runner import runner
from ..models import ChangeReport, Project, User
from ..schemas import (
    AskIn,
    AskOut,
    ChangeReportOut,
    IndexRequest,
    ProjectCreate,
    ProjectDetailOut,
    ProjectOut,
    ProjectUpdate,
)
from ..security import create_service_token
from ..services import graphdb, plugin_gen, rlm

log = logging.getLogger("projectai.api.projects")

router = APIRouter(prefix="/projects", tags=["projects"])

INDEX_JOB_TYPES = ["index", "knowledge_update"]


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[ProjectOut]:
    res = await session.execute(
        select(Project).where(Project.owner_id == user.id).order_by(desc(Project.updated_at))
    )
    return [ProjectOut.model_validate(p) for p in res.scalars()]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    root = Path(data.root_path)
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Каталог не найден: {data.root_path}")
    project = Project(
        owner_id=user.id,
        name=data.name.strip(),
        description=data.description.strip(),
        root_path=str(root.resolve()),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    # сервисный токен для MCP/плагина
    project.meta = {"service_token": create_service_token(user.id, project.id)}
    await session.commit()
    await session.refresh(project)

    # сразу запускаем первичную индексацию в фоне
    await runner.submit(project.id, "index", {"mode": "initial"})
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetailOut)
async def get_project_detail(project: Project = Depends(get_project)) -> ProjectDetailOut:
    out = ProjectDetailOut.model_validate(project)
    # сервисный токен наружу не отдаём
    meta = dict(out.meta)
    meta.pop("service_token", None)
    out.meta = meta
    try:
        out.stats = await graphdb.get_stats(str(project.id))
    except Exception as e:
        log.warning("Статистика графа недоступна: %s", e)
        out.stats = {}
    return out


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    data: ProjectUpdate,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    db_project = await session.get(Project, project.id)
    if data.name is not None:
        db_project.name = data.name.strip()
    if data.description is not None:
        db_project.description = data.description.strip()
    await session.commit()
    await session.refresh(db_project)
    return ProjectOut.model_validate(db_project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_session)
) -> None:
    await graphdb.delete_project_graph(str(project.id))
    await session.execute(delete(Project).where(Project.id == project.id))
    await session.commit()
    s = get_settings()
    for sub in ("materials", "mcp"):
        p = s.data_path / sub / str(project.id)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


@router.post("/{project_id}/index")
async def start_index(
    data: IndexRequest, project: Project = Depends(get_project)
) -> dict:
    if data.mode not in ("initial", "update", "reverify"):
        raise HTTPException(status_code=400, detail="mode: initial | update | reverify")
    if await runner.has_active(project.id, ["index"]):
        raise HTTPException(status_code=409, detail="Индексация уже идёт")
    params: dict = {"mode": data.mode}
    if data.ai_limit is not None:
        params["ai_limit"] = max(0, min(500, data.ai_limit))
    job = await runner.submit(project.id, "index", params)
    return {"job_id": str(job.id), "status": job.status}


@router.get("/{project_id}/changes", response_model=list[ChangeReportOut])
async def list_changes(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_session)
) -> list[ChangeReportOut]:
    res = await session.execute(
        select(ChangeReport)
        .where(ChangeReport.project_id == project.id)
        .order_by(desc(ChangeReport.created_at))
        .limit(20)
    )
    return [ChangeReportOut.model_validate(r) for r in res.scalars()]


@router.get("/{project_id}/graph")
async def graph_view(project: Project = Depends(get_project), limit: int = 400) -> dict:
    return await graphdb.get_graph_view(str(project.id), min(limit, 1500))


@router.get("/{project_id}/graph/search")
async def graph_search(
    q: str, project: Project = Depends(get_project), limit: int = 15
) -> list[dict]:
    try:
        return await graphdb.fulltext_search(str(project.id), q, min(limit, 50))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Поиск по графу недоступен: {e}")


@router.post("/{project_id}/graph/cypher")
async def graph_cypher(
    body: dict, project: Project = Depends(get_project)
) -> list[dict]:
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="Пустой запрос")
    try:
        return await graphdb.run_readonly_cypher(str(project.id), query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Cypher: {e}")


@router.post("/{project_id}/ask", response_model=AskOut)
async def ask(data: AskIn, project: Project = Depends(get_project)) -> AskOut:
    """RLM-вопрос по проекту: рекурсивный анализ без чата."""
    try:
        result = await rlm.answer(project, data.question, data.paths)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RLM-запрос не удался: {e}")
    return AskOut(**result)


@router.get("/{project_id}/plugin")
async def plugin_info(project: Project = Depends(get_project)) -> dict:
    return plugin_gen.plugin_install_info(project)


@router.post("/{project_id}/plugin/regenerate")
async def plugin_regenerate(project: Project = Depends(get_project)) -> dict:
    job = await runner.submit(project.id, "plugin_generate", {})
    return {"job_id": str(job.id)}
