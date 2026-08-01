from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_project
from ..models import Project, ProjectFile
from ..schemas import ProjectFileOut

router = APIRouter(prefix="/projects/{project_id}/files", tags=["files"])


@router.get("")
async def list_files(
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
    q: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    cond = [ProjectFile.project_id == project.id]
    if q:
        like = f"%{q}%"
        cond.append(ProjectFile.rel_path.ilike(like) | ProjectFile.summary.ilike(like))
    if kind:
        cond.append(ProjectFile.kind == kind)
    if status:
        cond.append(ProjectFile.analysis_status == status)

    total = (await session.execute(select(func.count()).where(*cond))).scalar() or 0
    res = await session.execute(
        select(ProjectFile)
        .where(*cond)
        .order_by(ProjectFile.rel_path)
        .limit(min(limit, 500))
        .offset(offset)
    )
    items = [ProjectFileOut.model_validate(f) for f in res.scalars()]
    return {"total": total, "items": items}
