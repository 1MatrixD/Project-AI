from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_project
from ..models import Decision, Project
from ..schemas import DecisionIn, DecisionOut, DecisionUpdateIn
from ..services import graphdb, vectors
from ..services.decisions import add_decision

router = APIRouter(prefix="/projects/{project_id}/decisions", tags=["decisions"])


@router.get("", response_model=list[DecisionOut])
async def list_decisions(
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> list[DecisionOut]:
    res = await session.execute(
        select(Decision)
        .where(Decision.project_id == project.id)
        .order_by(desc(Decision.updated_at))
    )
    return [DecisionOut.model_validate(d) for d in res.scalars()]


@router.post("", response_model=DecisionOut, status_code=201)
async def create_decision(
    data: DecisionIn, project: Project = Depends(get_project)
) -> DecisionOut:
    decision = await add_decision(project.id, data.topic, data.text, source="manual")
    return DecisionOut.model_validate(decision)


@router.patch("/{decision_id}", response_model=DecisionOut)
async def update_decision(
    decision_id: uuid.UUID,
    data: DecisionUpdateIn,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> DecisionOut:
    decision = await session.get(Decision, decision_id)
    if decision is None or decision.project_id != project.id:
        raise HTTPException(status_code=404, detail="Соглашение не найдено")
    if data.topic is not None:
        decision.topic = data.topic.strip()[:200]
    if data.text is not None:
        decision.text = data.text
    await session.commit()
    await session.refresh(decision)
    try:
        await graphdb.upsert_decision_node(
            str(project.id), str(decision.id), decision.topic, decision.text
        )
    except Exception:
        pass
    await vectors.upsert(
        str(project.id),
        [{"kind": "decision", "key": str(decision.id), "title": decision.topic, "text": decision.text}],
    )
    return DecisionOut.model_validate(decision)


@router.delete("/{decision_id}", status_code=204)
async def delete_decision(
    decision_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> None:
    decision = await session.get(Decision, decision_id)
    if decision is None or decision.project_id != project.id:
        raise HTTPException(status_code=404, detail="Соглашение не найдено")
    await session.delete(decision)
    await session.commit()
    try:
        await graphdb.delete_decision_node(str(project.id), str(decision_id))
    except Exception:
        pass
    await vectors.delete(str(project.id), kind="decision", keys=[str(decision_id)])
