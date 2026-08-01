from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select, update

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import runner
from ..models import Project, TaskItem
from ..schemas import normalize_plan
from . import claude_cli, graphdb, rlm
from .prompts import (
    TASK_ENRICH_INVESTIGATION_QUESTION,
    TASK_ENRICH_PROMPT,
    TASK_ENRICH_SYSTEM,
)

log = logging.getLogger("projectai.enrich")

"""RLM-проработка задач.

Короткая задача с созвона → детальная инженерная задача, основанная на реальном
устройстве кодовой базы: RLM-исследование (корень выбирает файлы по карте знаний,
под-агенты их читают) даёт факты со ссылками на файлы, финальный синтез собирает
описание и пошаговый план в стиле «как реально решают задачу». Существующие задачи
(сделанные и открытые) участвуют в контексте — для дубликатов, пересечений и
продолжений.
"""


async def list_existing_tasks_text(project_id: uuid.UUID, exclude: uuid.UUID | None = None) -> str:
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(TaskItem)
            .where(TaskItem.project_id == project_id)
            .order_by(TaskItem.created_at.desc())
            .limit(80)
        )
        rows = [t for t in res.scalars() if t.id != exclude]
    status_ru = {
        "planned": "запланирована",
        "in_progress": "в работе",
        "review": "на ревью",
        "done": "СДЕЛАНА",
        "cancelled": "отменена",
    }
    lines = [
        f"- «{t.title}» [{status_ru.get(t.status, t.status)}] {(t.description or '')[:120]}"
        for t in rows
    ]
    return "\n".join(lines) or "(задач ещё нет)"


async def enrich_one(project: Project, task: TaskItem) -> dict:
    """Прорабатывает одну задачу. Возвращает статистику."""
    s = get_settings()
    pid = str(project.id)

    # 1. RLM-исследование кодовой базы по задаче
    question = TASK_ENRICH_INVESTIGATION_QUESTION.format(
        title=task.title, description=(task.description or "")[:2000]
    )
    try:
        investigation = await rlm.answer(project, question)
        investigation_text = investigation["answer"]
        investigated_paths = sorted(
            {p for sq in investigation.get("sub_queries", []) for p in sq.get("paths", [])}
        )
    except Exception as e:
        log.warning("RLM-исследование задачи %s упало: %s", task.id, e)
        investigation_text = "(исследование не удалось — опирайся на карту знаний)"
        investigated_paths = []

    # 2. Синтез детальной задачи
    context = await graphdb.get_project_summary_context(pid, 3000)
    existing = await list_existing_tasks_text(project.id, exclude=task.id)
    prompt = TASK_ENRICH_PROMPT.format(
        project_name=project.name,
        title=task.title,
        description=(task.description or "(без описания)")[:2000],
        project_context=context,
        investigation=investigation_text[:20000],
        existing_tasks=existing,
    )
    obj, _ = await claude_cli.run_json_prompt(
        prompt,
        system=TASK_ENRICH_SYSTEM,
        tools=[],
        model=s.ai_model,
        reasoning="medium",
        max_turns=1,
        timeout=s.claude_timeout_sec,
    )
    if not isinstance(obj, dict):
        raise claude_cli.ClaudeError("Ожидался JSON-объект проработки")

    description = str(obj.get("description", "")).strip()
    plan = normalize_plan(obj.get("plan"))
    files = [str(f)[:500] for f in (obj.get("files") or [])[:40]]
    related = [
        {
            "title": str(r.get("title", ""))[:300],
            "relation": str(r.get("relation", "overlaps"))[:20],
            "note": str(r.get("note", ""))[:300],
        }
        for r in (obj.get("related_tasks") or [])[:10]
        if isinstance(r, dict) and r.get("title")
    ]
    duplicate_of = obj.get("duplicate_of") or None

    async with get_sessionmaker()() as session:
        db_task = await session.get(TaskItem, task.id)
        if db_task is None:
            return {"updated": 0}
        if description:
            db_task.description = description[:8000]
        if plan:
            db_task.plan = plan
        db_task.extra = {
            **(db_task.extra or {}),
            "enriched": True,
            "original_description": task.description,
            "files": files or investigated_paths[:40],
            "related": related,
            "duplicate_of": str(duplicate_of)[:300] if duplicate_of else None,
        }
        await session.commit()

    await graphdb.upsert_task_node(
        pid, str(task.id), task.title, task.status, (files or investigated_paths)[:30]
    )
    return {"updated": 1, "files": len(files), "related": len(related)}


async def enrich_tasks(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    s = get_settings()
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Проект не найден")
        q = select(TaskItem).where(TaskItem.project_id == project_id)
        task_ids = params.get("task_ids")
        if task_ids:
            q = q.where(TaskItem.id.in_([uuid.UUID(str(t)) for t in task_ids]))
        else:
            q = q.where(TaskItem.status.in_(["planned", "in_progress"]))
        res = await session.execute(q.order_by(TaskItem.created_at))
        tasks = [
            t for t in res.scalars() if task_ids or not (t.extra or {}).get("enriched")
        ]

    if not tasks:
        return {"enriched": 0, "errors": 0, "total": 0}

    sem = asyncio.Semaphore(s.ai_concurrency)
    done = 0
    errors = 0

    async def run_one(t: TaskItem) -> None:
        nonlocal done, errors
        async with sem:
            try:
                await enrich_one(project, t)
                done += 1
            except Exception as e:
                log.warning("Проработка задачи «%s» упала: %s", t.title, e)
                errors += 1
        await runner.report(
            job_id,
            min(0.98, (done + errors) / len(tasks)),
            f"RLM-проработка задач: {done + errors}/{len(tasks)}",
        )

    await asyncio.gather(*(run_one(t) for t in tasks))
    return {"enriched": done, "errors": errors, "total": len(tasks)}
