from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select, update

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import runner
from ..models import Project, TaskItem
from . import claude_cli, graphdb, rlm
from .decisions import get_decisions_text
from .prompts import (
    TASK_ENRICH_INVESTIGATION_QUESTION,
    TASK_ENRICH_PROMPT,
    TASK_ENRICH_SYSTEM,
    TASK_TEXT_LIMIT,
)

log = logging.getLogger("projectai.enrich")

"""RLM-проработка задач.

Короткая задача с созвона → досье для исполнителя (человека или ИИ-агента):
RLM-исследование (корень выбирает файлы по карте знаний, под-агенты их читают)
даёт факты со ссылками на файлы, финальный синтез собирает досье — где смотреть,
нюансы, как проверить, развилки. Решение НЕ предписывается: план от разведчика
становится потолком для исполнителя, факты — полом. Существующие задачи
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


def human_input_block(task: TaskItem) -> str:
    """Прямая речь людей по задаче: заметки владельца и уточнения из материалов.

    Живёт в extra, а не в description, потому что описание проработка пересобирает
    целиком — вписанное руками там не выживало. Здесь же оно переживает любое
    число проработок и каждый раз идёт в промпт.
    """
    extra = task.extra or {}
    lines: list[str] = []
    notes = str(extra.get("notes") or "").strip()
    if notes:
        lines.append(f"[заметка владельца] {notes[:TASK_TEXT_LIMIT]}")
    for c in (extra.get("clarifications") or [])[:20]:
        text = str((c or {}).get("text") or "").strip()
        if text:
            source = str((c or {}).get("source") or "материал")
            lines.append(f"[уточнение из «{source}»] {text[:TASK_TEXT_LIMIT]}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "\nЗаметки владельца и уточнения из материалов — прямая речь людей,"
        " которые знают продукт:\n" + body + "\n"
    )


async def enrich_one(
    project: Project, task: TaskItem, on_progress: rlm.StageCb | None = None
) -> dict:
    """Прорабатывает одну задачу. Возвращает статистику.

    `on_progress` получает долю выполненного (0..1) и описание текущего шага:
    проработка идёт минутами, и без отметок она выглядит зависшей.
    """
    s = get_settings()
    pid = str(project.id)

    async def report(value: float, detail: str) -> None:
        if on_progress is not None:
            await on_progress(value, detail)

    decisions = await get_decisions_text(project.id)

    notes_block = human_input_block(task)

    # 1. RLM-исследование кодовой базы по задаче (самая долгая фаза — до 60%)
    question = TASK_ENRICH_INVESTIGATION_QUESTION.format(
        title=task.title,
        description=(task.description or "")[:TASK_TEXT_LIMIT],
        notes_block=notes_block,
        decisions=decisions,
    )

    async def rlm_stage(value: float, detail: str) -> None:
        await report(0.05 + 0.55 * value, f"исследование — {detail}")

    await report(0.03, "исследование — выбираю файлы по карте знаний")
    try:
        investigation = await rlm.answer(project, question, on_stage=rlm_stage)
        investigation_text = investigation["answer"]
        investigated_paths = sorted(
            {p for sq in investigation.get("sub_queries", []) for p in sq.get("paths", [])}
        )
        investigation_ok = True
        await report(0.62, f"исследование готово, файлов: {len(investigated_paths)}")
    except Exception as e:
        log.warning("RLM-исследование задачи %s упало: %s", task.id, e)
        investigation_text = "(исследование не удалось — опирайся на карту знаний)"
        investigated_paths = []
        investigation_ok = False
        await report(0.62, "исследование не удалось — опираюсь на карту знаний")

    # 2. Синтез детальной задачи
    await report(0.68, "собираю досье: где смотреть, нюансы, как проверить")
    context = await graphdb.get_project_summary_context(pid, 3000)
    existing = await list_existing_tasks_text(project.id, exclude=task.id)

    async def synthesize(facts: str) -> dict:
        prompt = TASK_ENRICH_PROMPT.format(
            project_name=project.name,
            title=task.title,
            description=(task.description or "(без описания)")[:TASK_TEXT_LIMIT],
            notes_block=notes_block,
            project_context=context,
            decisions=decisions,
            investigation=facts[:20000],
            existing_tasks=existing,
        )
        # Синтез иногда отдаёт синтаксически битый JSON (досье длинное). Ответ
        # стоит секунды, а исследование перед ним — минуты, поэтому падать всей
        # проработкой из-за одной запятой нельзя: пробуем ещё раз.
        last_error: Exception = claude_cli.ClaudeError("Синтез не выполнялся")
        for attempt in (1, 2):
            try:
                result, _ = await claude_cli.run_json_prompt(
                    prompt,
                    system=TASK_ENRICH_SYSTEM,
                    tools=[],
                    model=s.ai_model,
                    reasoning="medium",
                    max_turns=s.claude_max_turns,
                    timeout=s.claude_timeout_sec,
                )
                if not isinstance(result, dict):
                    raise claude_cli.ClaudeError("Ожидался JSON-объект проработки")
                return result
            except claude_cli.ClaudeError as e:
                last_error = e
                log.warning(
                    "Синтез досье «%s» не распарсился (попытка %d): %s",
                    task.title[:60], attempt, str(e)[:200],
                )
        raise last_error

    obj = await synthesize(investigation_text)

    # 3. Доисследование: синтез сам перечисляет, чего не нашёл в коде. Это второй
    # уровень RLM — узкий и только по этим вопросам, один раз. Без него модель
    # выдаёт догадку («наверное, где-то есть») вместо факта.
    unresolved = [
        str(u).strip()[:300] for u in (obj.get("unresolved") or [])[:5] if str(u).strip()
    ]
    if unresolved and investigation_ok and s.enrich_followup:
        await report(0.72, f"доисследование: вопросов без ответа — {len(unresolved)}")

        async def followup_stage(value: float, detail: str) -> None:
            await report(0.72 + 0.14 * value, f"доисследование — {detail}")

        followup_question = "Ответь строго на эти вопросы по коду проекта:\n" + "\n".join(
            f"- {u}" for u in unresolved
        )
        try:
            extra_inv = await rlm.answer(project, followup_question, on_stage=followup_stage)
            investigation_text += "\n\nДоисследование:\n" + str(extra_inv.get("answer", ""))
            investigated_paths = sorted(
                set(investigated_paths)
                | {p for sq in extra_inv.get("sub_queries", []) for p in sq.get("paths", [])}
            )
            await report(0.88, "пересобираю описание с учётом доисследования")
            obj = await synthesize(investigation_text)
        except Exception as e:
            log.warning("Доисследование задачи %s упало: %s", task.id, e)

    description = str(obj.get("description", "")).strip()
    reading = str(obj.get("reading", "")).strip()[:2000]
    hyp = obj.get("hypothesis") or {}
    hypothesis = (
        {
            "text": str(hyp.get("text", "")).strip()[:1000],
            "confidence": str(hyp.get("confidence", "medium"))[:10],
        }
        if isinstance(hyp, dict) and str(hyp.get("text", "")).strip()
        else None
    )
    where_to_look = [
        {"path": str(w.get("path", ""))[:500], "why": str(w.get("why", ""))[:400]}
        for w in (obj.get("where_to_look") or [])[:20]
        if isinstance(w, dict) and str(w.get("path", "")).strip()
    ]
    reference = str(obj.get("reference", "")).strip()[:1500]
    how_to_verify = [
        {"what": str(v.get("what", ""))[:300], "how": str(v.get("how", ""))[:500]}
        for v in (obj.get("how_to_verify") or [])[:10]
        if isinstance(v, dict) and str(v.get("what", "")).strip()
    ]
    files = [str(f)[:500] for f in (obj.get("files") or [])[:40]] or [
        w["path"] for w in where_to_look
    ]
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
    open_questions = [
        {
            "question": str(q.get("question", ""))[:400],
            "options": [str(o)[:300] for o in (q.get("options") or [])[:4]],
            "lean": str(q.get("lean", ""))[:300],
        }
        for q in (obj.get("open_questions") or [])[:6]
        if isinstance(q, dict) and str(q.get("question", "")).strip()
    ]
    impact = [
        {"what": str(i.get("what", ""))[:300], "why": str(i.get("why", ""))[:400]}
        for i in (obj.get("impact") or [])[:10]
        if isinstance(i, dict) and str(i.get("what", "")).strip()
    ]

    async with get_sessionmaker()() as session:
        db_task = await session.get(TaskItem, task.id)
        if db_task is None:
            return {"updated": 0}
        if description:
            db_task.description = description[:8000]
        # план сознательно не пишем: досье не предписывает решение (ручной план
        # и подзадачи планировщика остаются как были)
        db_task.extra = {
            **(db_task.extra or {}),
            "enriched": True,
            "original_description": task.description,
            "reading": reading,
            "hypothesis": hypothesis,
            "where_to_look": where_to_look,
            "reference": reference,
            "how_to_verify": how_to_verify,
            "files": files or investigated_paths[:40],
            "related": related,
            "duplicate_of": str(duplicate_of)[:300] if duplicate_of else None,
            "open_questions": open_questions,
            "impact": impact,
        }
        await session.commit()

    await report(0.95, "сохраняю досье и связи с файлами")
    await graphdb.upsert_task_node(
        pid, str(task.id), task.title, task.status, (files or investigated_paths)[:30]
    )
    return {
        "updated": 1,
        "files": len(files),
        "where_to_look": len(where_to_look),
        "how_to_verify": len(how_to_verify),
        "related": len(related),
        "open_questions": len(open_questions),
        "impact": len(impact),
    }


async def select_tasks(session, project_id: uuid.UUID, task_ids: list | None) -> list[TaskItem]:
    """Что пойдёт в проработку. Без `task_ids` — открытые задачи без проработки:
    именно это делает кнопка «Проработать новые (RLM)»."""
    q = select(TaskItem).where(TaskItem.project_id == project_id)
    if task_ids:
        q = q.where(TaskItem.id.in_([uuid.UUID(str(t)) for t in task_ids]))
    else:
        q = q.where(TaskItem.status.in_(["planned", "in_progress"]))
    res = await session.execute(q.order_by(TaskItem.created_at))
    return [t for t in res.scalars() if task_ids or not (t.extra or {}).get("enriched")]


async def count_pending(project_id: uuid.UUID) -> int:
    """Сколько задач возьмёт «Проработать новые» — чтобы UI не обещал работу,
    которой не будет."""
    async with get_sessionmaker()() as session:
        return len(await select_tasks(session, project_id, None))


async def enrich_tasks(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    s = get_settings()
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Проект не найден")
        tasks = await select_tasks(session, project_id, params.get("task_ids"))

    if not tasks:
        return {"enriched": 0, "errors": 0, "total": 0}

    sem = asyncio.Semaphore(s.ai_concurrency)
    done = 0
    errors = 0
    total = len(tasks)

    # Задачи прорабатываются параллельно, поэтому общий прогресс — среднее
    # по задачам, а не счётчик завершённых: иначе полоса стоит на нуле
    # всё время работы и выглядит как зависание.
    progress_by_task: dict[uuid.UUID, float] = {t.id: 0.0 for t in tasks}
    progress_lock = asyncio.Lock()

    def label(t: TaskItem) -> str:
        title = " ".join(t.title.split())
        return title[:50] + ("…" if len(title) > 50 else "")

    async def report_for(t: TaskItem, value: float, detail: str) -> None:
        async with progress_lock:
            progress_by_task[t.id] = max(progress_by_task[t.id], min(1.0, value))
            overall = sum(progress_by_task.values()) / total
        text = detail if total == 1 else f"«{label(t)}» — {detail}"
        await runner.report(job_id, min(0.98, overall), text)

    await runner.report(job_id, 0.01, f"RLM-проработка, задач: {total}")

    async def run_one(t: TaskItem) -> None:
        nonlocal done, errors
        if runner.is_cancelled(job_id):
            return
        failure = ""
        async with sem:
            try:
                await enrich_one(project, t, on_progress=lambda v, d, _t=t: report_for(_t, v, d))
                done += 1
            except Exception as e:
                log.warning("Проработка задачи «%s» упала: %s", t.title, e)
                errors += 1
                failure = str(e)[:120]
        finished = done + errors
        tail = "" if total == 1 else f" ({finished}/{total})"
        await report_for(t, 1.0, (f"ошибка: {failure}" if failure else "проработана") + tail)

    await asyncio.gather(*(run_one(t) for t in tasks))
    runner.check_cancelled(job_id)
    stats: dict = {"enriched": done, "errors": errors, "total": len(tasks)}
    if errors:
        stats["final_detail"] = (
            f"проработано {done} из {total}, с ошибкой: {errors} — "
            "карточки без досье отправь на проработку ещё раз"
        )
    return stats
