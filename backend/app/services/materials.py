from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select, update

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import runner
from ..models import Material, Project, TaskItem, utcnow
from . import claude_cli, extract, graphdb
from .prompts import TASK_EXTRACTION_PROMPT, TASK_EXTRACTION_SYSTEM

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


async def extract_tasks_from_text(
    project: Project, title: str, source_kind: str, text: str
) -> dict:
    """ИИ-выжимка материала: summary + задачи. Возвращает {'summary', 'tasks': [...]}."""
    from .task_enrich import list_existing_tasks_text

    s = get_settings()
    context = await graphdb.get_project_summary_context(str(project.id), 3000)
    existing = await list_existing_tasks_text(project.id)
    prompt = TASK_EXTRACTION_PROMPT.format(
        project_name=project.name,
        source_kind=source_kind,
        title=title,
        project_context=context or "(проект ещё не проиндексирован)",
        existing_tasks=existing,
        text=text[:MAX_TEXT_FOR_AI],
    )
    obj, _ = await claude_cli.run_json_prompt(
        prompt,
        system=TASK_EXTRACTION_SYSTEM,
        tools=[],
        model=s.ai_model,
        reasoning="medium",
        max_turns=1,
        timeout=s.claude_timeout_sec,
    )
    if not isinstance(obj, dict):
        raise claude_cli.ClaudeError("Ожидался JSON-объект с summary/tasks")
    return obj


async def process_material(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    """Пайплайн материала: текст (извлечение или транскрибация) → граф → задачи в канбан."""
    material_id = uuid.UUID(params["material_id"])
    do_tasks = params.get("extract_tasks", True)
    maker = get_sessionmaker()

    async with maker() as session:
        material = await session.get(Material, material_id)
        project = await session.get(Project, project_id)
        if material is None or project is None:
            raise RuntimeError("Материал или проект не найден")
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
            await runner.report(job_id, 0.1, "Транскрибация (whisper)")
            from . import transcribe

            result = await asyncio.to_thread(transcribe.transcribe_file, material.stored_path)
            text = result["text"]
            stats["transcribe"] = {
                "language": result["language"],
                "duration_sec": result["duration"],
                "segments": result["segments_count"],
            }
        else:
            await runner.report(job_id, 0.1, "Извлечение текста")
            text = await asyncio.to_thread(extract.extract_text, material.stored_path)

        text = text.strip()
        if not text:
            raise RuntimeError("Пустой текст после обработки")

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

        summary = ""
        created_tasks = 0
        created_ids: list[str] = []
        if do_tasks:
            await runner.report(job_id, 0.55, "ИИ: выжимка и извлечение задач")
            try:
                from ..schemas import normalize_plan

                parsed = await extract_tasks_from_text(project, material.filename, dtype, text)
                summary = str(parsed.get("summary", ""))[:4000]
                tasks = parsed.get("tasks") or []
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
                        )
                        session.add(item)
                        await session.flush()
                        await graphdb.upsert_task_node(
                            str(project_id), str(item.id), item.title, item.status
                        )
                        created_tasks += 1
                        created_ids.append(str(item.id))
                    await session.commit()
            except claude_cli.ClaudeError as e:
                log.warning("Извлечение задач из %s не удалось: %s", material.filename, e)
                stats["task_extraction_error"] = str(e)[:500]

        if created_ids:
            # RLM-проработка новых задач: короткие формулировки с созвона →
            # детальные задачи со ссылками на файлы
            await runner.submit(project_id, "enrich_tasks", {"task_ids": created_ids})
            stats["enrich_job_submitted"] = True

        await graphdb.upsert_document(
            str(project_id), str(material_id), material.filename, dtype, summary or text[:1000], []
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
    except Exception as e:
        async with maker() as session:
            await session.execute(
                update(Material)
                .where(Material.id == material_id)
                .values(status="error", error=str(e)[:2000])
            )
            await session.commit()
        raise
