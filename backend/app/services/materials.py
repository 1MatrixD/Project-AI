from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select, update

from ..config import get_settings
from ..db import get_sessionmaker
from .. import i18n
from ..jobs_runner import JobCancelled, runner
from ..models import Material, Project, TaskItem, utcnow
from . import claude_cli, extract, graphdb
from .prompts import TASK_EXTRACTION_PROMPT, TASK_EXTRACTION_SYSTEM, localized

log = logging.getLogger("projectai.materials")

MAX_TEXT_FOR_AI = 150_000  # символов текста материала в промпт


def material_text_path(project_id: uuid.UUID, material_id: uuid.UUID) -> str:
    s = get_settings()
    d = s.data_path / "materials" / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{material_id}.txt")


async def _next_task_order(session, project_id: uuid.UUID, status: str) -> float:
    res = await session.execute(
        select(func.max(TaskItem.order)).where(
            TaskItem.project_id == project_id, TaskItem.status == status
        )
    )
    mx = res.scalar()
    return (mx or 0.0) + 1.0


async def clarified_tasks_text(project_id: uuid.UUID, material_id: uuid.UUID) -> str:
    """Задачи, рождённые указанным материалом, — с ПОЛНЫМ описанием.

    Обычный список существующих задач даёт по 120 символов описания: этого хватает,
    чтобы не задвоить, но не хватает, чтобы решить «дополнить или завести новую».
    Материал-уточнение целится именно в эти задачи, поэтому их показываем целиком.
    """
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(TaskItem)
            .where(TaskItem.project_id == project_id)
            .order_by(TaskItem.created_at)
            .limit(200)
        )
        rows = [
            t
            for t in res.scalars()
            if str(((t.extra or {}).get("from_material") or {}).get("id", "")) == str(material_id)
        ]
    if not rows:
        return ""
    blocks = [
        f"### {t.title}\n{(t.description or '(без описания)')[:4000]}" for t in rows
    ]
    return "\n\n".join(blocks)


async def extract_tasks_from_text(
    project: Project,
    title: str,
    source_kind: str,
    text: str,
    clarifies_text: str = "",
) -> dict:
    """ИИ-выжимка материала: summary + новые задачи + дополнения к существующим."""
    from .decisions import get_decisions_text
    from .task_enrich import list_existing_tasks_text

    s = get_settings()
    context = await graphdb.get_project_summary_context(str(project.id), 3000)
    existing = await list_existing_tasks_text(project.id)
    decisions = await get_decisions_text(project.id)
    clarifies_block = (
        "\nЭтот материал загружен как уточнение к более раннему. Задачи, которые\n"
        "родились из того материала, приведены полностью — скорее всего дополнять\n"
        "нужно именно их:\n" + clarifies_text + "\n"
        if clarifies_text
        else ""
    )
    prompt = localized(TASK_EXTRACTION_PROMPT).format(
        project_name=project.name,
        source_kind=source_kind,
        title=title,
        project_context=context or "(проект ещё не проиндексирован)",
        existing_tasks=existing,
        clarifies_block=clarifies_block,
        decisions=decisions,
        text=text[:MAX_TEXT_FOR_AI],
    )
    obj, _ = await claude_cli.run_json_prompt(
        prompt,
        system=TASK_EXTRACTION_SYSTEM,
        tools=[],
        model=s.ai_model,
        reasoning="medium",
        max_turns=s.claude_max_turns,
        timeout=s.claude_timeout_sec,
    )
    if not isinstance(obj, dict):
        raise claude_cli.ClaudeError(i18n._("Ожидался JSON-объект с summary/tasks"))
    return obj


async def _apply_task_updates(
    project_id: uuid.UUID, updates: list, origin: dict
) -> list[str]:
    """Дополнения из материала → в существующие задачи.

    Задача ищется по дословному совпадению названия (так требует промпт).

    Дополнение кладётся в extra.clarifications, а не дописывается в description:
    описание проработка пересобирает целиком, и дописанный туда текст она бы
    затёрла — тем вернее, чем быстрее материал приходит следом за созвоном.
    Уточнения живут рядом с заметками владельца, оба блока проработка читает и
    никогда не перезаписывает. Флаг enriched снимается: досье собрано по старому
    тексту, с новой логикой его надо пересобрать.
    """
    touched: list[str] = []
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(TaskItem).where(TaskItem.project_id == project_id)
        )
        by_title = {t.title.strip().lower(): t for t in res.scalars()}
        for u in updates[:40]:
            if not isinstance(u, dict):
                continue
            title = str(u.get("task_title", "")).strip()
            addition = str(u.get("add", "")).strip()
            if not title or not addition:
                continue
            task = by_title.get(title.lower())
            if task is None:
                log.info("Дополнение не нашло задачу «%s» — пропускаю", title[:80])
                continue
            extra = dict(task.extra or {})
            clarifications = list(extra.get("clarifications") or [])
            clarifications.append({"text": addition[:8000], "source": origin["filename"]})
            extra["clarifications"] = clarifications[-20:]
            extra["enriched"] = False
            extra["updated_by_materials"] = (extra.get("updated_by_materials") or []) + [origin]
            task.extra = extra
            touched.append(str(task.id))
        await session.commit()
    return touched


async def process_material(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    """Пайплайн материала: текст (извлечение или транскрибация) → граф → задачи в канбан."""
    material_id = uuid.UUID(params["material_id"])
    do_tasks = params.get("extract_tasks", True)
    maker = get_sessionmaker()

    async with maker() as session:
        material = await session.get(Material, material_id)
        project = await session.get(Project, project_id)
        if material is None or project is None:
            raise RuntimeError(i18n._("Материал или проект не найден"))
        material.status = "processing"
        material.error = None
        await session.commit()

    stats: dict = {}
    try:
        tpath = material_text_path(project_id, material_id)
        is_av = extract.is_audio_video(material.filename)
        dtype = "transcript" if is_av else "doc"

        import os

        if params.get("reuse_text") and os.path.isfile(tpath):
            # повторная обработка: текст уже извлечён/транскрибирован
            text = await asyncio.to_thread(
                lambda: open(tpath, "r", encoding="utf-8").read()
            )
            stats["reused_text"] = True
        elif is_av:
            await runner.report(job_id, 0.1, i18n._("Транскрибация (whisper)"))
            from . import transcribe

            result = await asyncio.to_thread(transcribe.transcribe_file, material.stored_path)
            text = result["text"]
            stats["transcribe"] = {
                "language": result["language"],
                "duration_sec": result["duration"],
                "segments": result["segments_count"],
            }
        else:
            await runner.report(job_id, 0.1, i18n._("Извлечение текста"))
            text = await asyncio.to_thread(extract.extract_text, material.stored_path)

        text = text.strip()
        if not text:
            raise RuntimeError(i18n._("Пустой текст после обработки"))

        await asyncio.to_thread(
            lambda: open(tpath, "w", encoding="utf-8").write(text)
        )
        stats["text_chars"] = len(text)
        # текст доступен сразу, даже если дальнейшие ИИ-шаги упадут
        async with maker() as session:
            await session.execute(
                update(Material).where(Material.id == material_id).values(text_path=tpath)
            )
            await session.commit()

        runner.check_cancelled(job_id)
        summary = ""
        created_tasks = 0
        created_ids: list[str] = []
        if do_tasks:
            await runner.report(job_id, 0.55, i18n._("ИИ: выжимка и извлечение задач"))
            try:
                from ..schemas import normalize_plan

                clarifies_id = (material.meta or {}).get("clarifies")
                clarifies_text = (
                    await clarified_tasks_text(project_id, uuid.UUID(str(clarifies_id)))
                    if clarifies_id
                    else ""
                )
                parsed = await extract_tasks_from_text(
                    project, material.filename, dtype, text, clarifies_text
                )
                summary = str(parsed.get("summary", ""))[:4000]
                tasks = parsed.get("tasks") or []
                origin = {"id": str(material_id), "filename": material.filename}
                async with maker() as session:
                    for t in tasks:
                        if not isinstance(t, dict) or not t.get("title"):
                            continue
                        order = await _next_task_order(session, project_id, "planned")
                        item = TaskItem(
                            project_id=project_id,
                            title=str(t["title"])[:300],
                            description=str(t.get("description", ""))[:8000],
                            status="planned",
                            source="meeting" if dtype == "transcript" else "doc",
                            order=order,
                            plan=normalize_plan(t.get("plan")),
                            # откуда задача — по этой метке материал-уточнение
                            # находит «те самые задачи с созвона»
                            extra={"from_material": origin},
                        )
                        session.add(item)
                        await session.flush()
                        await graphdb.upsert_task_node(
                            str(project_id), str(item.id), item.title, item.status
                        )
                        created_tasks += 1
                        created_ids.append(str(item.id))
                    await session.commit()
                updated_ids = await _apply_task_updates(
                    project_id, parsed.get("updates") or [], origin
                )
                if updated_ids:
                    stats["tasks_updated"] = len(updated_ids)
                    created_ids.extend(updated_ids)
                # решения/договорённости с созвона → соглашения проекта
                from .decisions import add_decision

                decisions_created = 0
                for d in (parsed.get("decisions") or [])[:20]:
                    if isinstance(d, dict) and d.get("topic") and d.get("text"):
                        await add_decision(
                            project_id,
                            str(d["topic"])[:200],
                            str(d["text"])[:4000],
                            source="meeting" if dtype == "transcript" else "doc",
                        )
                        decisions_created += 1
                if decisions_created:
                    stats["decisions_created"] = decisions_created
            except claude_cli.ClaudeError as e:
                log.warning("Извлечение задач из %s не удалось: %s", material.filename, e)
                stats["task_extraction_error"] = str(e)[:500]

        if created_ids:
            # RLM-проработка: и новые задачи, и дополненные материалом — у последних
            # досье собрано по старому описанию и без новой логики уже неверно
            await runner.submit(project_id, "enrich_tasks", {"task_ids": created_ids})
            stats["enrich_job_submitted"] = True

        await graphdb.upsert_document(
            str(project_id), str(material_id), material.filename, dtype, summary or text[:1000], []
        )
        from . import vectors

        await vectors.upsert(
            str(project_id),
            [
                {
                    "kind": "doc",
                    "key": str(material_id),
                    "title": material.filename,
                    "text": summary or text[:1000],
                }
            ],
        )

        async with maker() as session:
            await session.execute(
                update(Material)
                .where(Material.id == material_id)
                .values(
                    status="ready",
                    text_path=tpath,
                    summary=summary or None,
                    processed_at=utcnow(),
                    meta={**stats},
                )
            )
            await session.commit()

        stats["tasks_created"] = created_tasks
        return stats
    except JobCancelled:
        # отмена — не ошибка: извлечённый текст сохранён, можно переобработать
        async with maker() as session:
            await session.execute(
                update(Material).where(Material.id == material_id).values(status="uploaded")
            )
            await session.commit()
        raise
    except Exception as e:
        async with maker() as session:
            await session.execute(
                update(Material)
                .where(Material.id == material_id)
                .values(status="error", error=str(e)[:2000])
            )
            await session.commit()
        raise
