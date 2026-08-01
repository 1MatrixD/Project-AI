from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from ..db import get_sessionmaker
from ..models import Decision
from . import graphdb

log = logging.getLogger("projectai.decisions")


async def get_decisions_text(project_id: uuid.UUID, limit: int = 50) -> str:
    """Блок «Соглашения проекта» для промптов: актуальные решения и смены подходов."""
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(Decision)
            .where(Decision.project_id == project_id)
            .order_by(Decision.updated_at.desc())
            .limit(limit)
        )
        rows = list(res.scalars())
    if not rows:
        return "(соглашений пока не зафиксировано)"
    return "\n".join(f"- {d.topic}: {d.text}" for d in rows)


async def add_decision(
    project_id: uuid.UUID, topic: str, text: str, source: str = "manual"
) -> Decision:
    async with get_sessionmaker()() as session:
        # апдейт по совпадению темы вместо дубликата
        res = await session.execute(
            select(Decision).where(
                Decision.project_id == project_id,
                Decision.topic.ilike(topic.strip()),
            )
        )
        existing = res.scalar_one_or_none()
        if existing:
            existing.text = text
            existing.source = source
            await session.commit()
            await session.refresh(existing)
            decision = existing
        else:
            decision = Decision(
                project_id=project_id, topic=topic.strip()[:200], text=text, source=source
            )
            session.add(decision)
            await session.commit()
            await session.refresh(decision)
    try:
        await graphdb.upsert_decision_node(
            str(project_id), str(decision.id), decision.topic, decision.text
        )
    except Exception:
        log.warning("Decision-узел не записался в граф", exc_info=True)
    from . import vectors

    await vectors.upsert(
        str(project_id),
        [{"kind": "decision", "key": str(decision.id), "title": decision.topic, "text": decision.text}],
    )
    return decision
