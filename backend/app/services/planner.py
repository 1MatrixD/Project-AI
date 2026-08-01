from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import runner
from ..models import Project, TaskItem
from ..schemas import normalize_plan
from . import claude_cli, graphdb, rlm
from .decisions import get_decisions_text
from .prompts import (
    TASK_PLAN_INVESTIGATION_QUESTION,
    TASK_PLAN_PROMPT,
    TASK_PLAN_SYSTEM,
)
from .task_enrich import list_existing_tasks_text

log = logging.getLogger("projectai.planner")

"""Планировщик: крупная задача (например, с созвона) → общий план → декомпозиция
в подзадачи канбана с зависимостями.

Отличие от RLM-проработки (task_enrich): проработка углубляет ОДНУ задачу,
планировщик разбивает её на несколько самостоятельных подзадач с порядком
выполнения (depends_on) — независимые можно брать в работу параллельно.
"""


async def plan_task(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    s = get_settings()
    task_id = uuid.UUID(str(params["task_id"]))
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        task = await session.get(TaskItem, task_id)
    if project is None or task is None or task.project_id != project_id:
        raise RuntimeError("Задача не найдена")

    pid = str(project_id)
    decisions = await get_decisions_text(project_id)

    # 1. RLM-исследование: из каких частей состоит работа и в каком порядке
    await runner.report(job_id, 0.1, f"Планировщик: исследование «{task.title[:60]}»")
    question = TASK_PLAN_INVESTIGATION_QUESTION.format(
        title=task.title, description=(task.description or "")[:2000], decisions=decisions
    )
    try:
        investigation = await rlm.answer(project, question)
        investigation_text = investigation["answer"]
    except Exception as e:
        log.warning("RLM-исследование для плана %s упало: %s", task_id, e)
        investigation_text = "(исследование не удалось — опирайся на карту знаний)"
    runner.check_cancelled(job_id)

    # 2. Синтез плана и декомпозиция
    await runner.report(job_id, 0.55, "Планировщик: декомпозиция на подзадачи")
    context = await graphdb.get_project_summary_context(pid, 3000)
    existing = await list_existing_tasks_text(project_id, exclude=task_id)
    prompt = TASK_PLAN_PROMPT.format(
        project_name=project.name,
        title=task.title,
        description=(task.description or "(без описания)")[:2000],
        project_context=context,
        decisions=decisions,
        investigation=investigation_text[:20000],
        existing_tasks=existing,
    )
    obj, _ = await claude_cli.run_json_prompt(
        prompt,
        system=TASK_PLAN_SYSTEM,
        tools=[],
        model=s.ai_model,
        reasoning="medium",
        max_turns=1,
        timeout=s.claude_timeout_sec,
    )
    if not isinstance(obj, dict) or not isinstance(obj.get("subtasks"), list):
        raise claude_cli.ClaudeError("Ожидался JSON-объект с подзадачами")
    runner.check_cancelled(job_id)

    plan_summary = str(obj.get("plan_summary", "")).strip()[:4000]
    raw = [
        st
        for st in obj["subtasks"][:12]
        if isinstance(st, dict) and str(st.get("title", "")).strip()
    ]
    if not raw:
        raise claude_cli.ClaudeError("Планировщик не вернул ни одной подзадачи")

    # 3. Создание подзадач: сначала все строки (чтобы получить id), затем зависимости
    await runner.report(job_id, 0.85, f"Планировщик: создаю подзадачи ({len(raw)})")
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(func.max(TaskItem.order)).where(
                TaskItem.project_id == project_id, TaskItem.status == "planned"
            )
        )
        base_order = res.scalar() or 0.0
        subtasks: list[TaskItem] = []
        for i, st in enumerate(raw):
            item = TaskItem(
                project_id=project_id,
                title=str(st["title"]).strip()[:300],
                description=str(st.get("description", ""))[:8000],
                source="plan",
                order=base_order + i + 1,
                plan=normalize_plan(st.get("plan")),
            )
            session.add(item)
            subtasks.append(item)
        await session.flush()

        ids = [item.id for item in subtasks]
        for i, (item, st) in enumerate(zip(subtasks, raw)):
            deps = sorted(
                {
                    int(d)
                    for d in (st.get("depends_on") or [])
                    if isinstance(d, (int, float)) and 0 <= int(d) < len(subtasks) and int(d) != i
                }
            )
            item.extra = {
                "parent_task": str(task_id),
                "parent_title": task.title[:300],
                "depends_on": [str(ids[d]) for d in deps],
                "files": [str(f)[:500] for f in (st.get("files") or [])[:30]],
            }

        db_task = await session.get(TaskItem, task_id)
        if db_task is not None:
            db_task.extra = {
                **(db_task.extra or {}),
                "planned": True,
                "plan_summary": plan_summary,
                "subtasks": [str(i) for i in ids],
            }
        await session.commit()
        created = [(str(item.id), item.title, dict(item.extra)) for item in subtasks]

    # 4. Граф: узлы подзадач + рёбра DEPENDS_ON / SUBTASK_OF
    for tid, title, extra in created:
        try:
            await graphdb.upsert_task_node(pid, tid, title, "planned", extra.get("files") or None)
            await graphdb.link_task_dependencies(
                pid, tid, extra.get("depends_on") or [], parent=str(task_id)
            )
        except Exception as e:
            log.warning("Граф: не удалось связать подзадачу %s: %s", tid, e)

    runner.publish(project_id, {"type": "tasks_changed"})
    return {"subtasks": len(created), "task": task.title[:200]}
