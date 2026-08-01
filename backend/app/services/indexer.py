from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select, update

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import JobCancelled, runner
from ..models import ChangeReport, Project, ProjectFile, TaskItem, WorkLogEntry, utcnow
from . import claude_cli, graphdb, vectors
from .prompts import (
    FILE_ANALYSIS_PROMPT,
    FILE_ANALYSIS_SYSTEM,
    SYNTHESIS_PROMPT,
    SYNTHESIS_SYSTEM,
    TASK_VERIFY_PROMPT,
    TASK_VERIFY_SYSTEM,
)
from .scanner import MAX_ANALYZABLE_SIZE, ScanDiff, diff_scan, scan_directory
from .detect import detect_project

log = logging.getLogger("projectai.indexer")

ANALYZABLE_KINDS = {"code", "config", "test", "doc", "other"}
ANALYZABLE_TEXT_EXT_EXCLUDED = {".pdf", ".docx", ".doc", ".rtf", ".xlsx", ".xls"}


async def _get_project(project_id: uuid.UUID) -> Project:
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise RuntimeError(f"Проект {project_id} не найден")
        return project


async def _set_project(project_id: uuid.UUID, **values: Any) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(update(Project).where(Project.id == project_id).values(**values))
        await session.commit()


async def _load_known(project_id: uuid.UUID) -> dict[str, tuple[float, int, str]]:
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(ProjectFile.rel_path, ProjectFile.mtime, ProjectFile.size, ProjectFile.sha256)
            .where(ProjectFile.project_id == project_id)
        )
        return {r.rel_path: (r.mtime, r.size, r.sha256) for r in res}


async def _apply_scan_to_db(project_id: uuid.UUID, diff: ScanDiff) -> None:
    async with get_sessionmaker()() as session:
        if diff.deleted:
            await session.execute(
                delete(ProjectFile).where(
                    ProjectFile.project_id == project_id,
                    ProjectFile.rel_path.in_(diff.deleted),
                )
            )
        for f in diff.added:
            session.add(
                ProjectFile(
                    project_id=project_id,
                    rel_path=f.rel_path,
                    sha256=f.sha256,
                    size=f.size,
                    mtime=f.mtime,
                    kind=f.kind,
                )
            )
        for f in diff.modified:
            await session.execute(
                update(ProjectFile)
                .where(ProjectFile.project_id == project_id, ProjectFile.rel_path == f.rel_path)
                .values(
                    sha256=f.sha256,
                    size=f.size,
                    mtime=f.mtime,
                    kind=f.kind,
                    analysis_status="pending",
                )
            )
        await session.commit()


def _graph_files(scanned) -> list[dict]:
    return [
        {
            "path": f.rel_path,
            "name": f.rel_path.rsplit("/", 1)[-1],
            "kind": f.kind,
            "size": f.size,
            "dir": f.rel_path.rsplit("/", 1)[0] if "/" in f.rel_path else "",
        }
        for f in scanned
    ]


def _is_ai_analyzable(rel_path: str, kind: str, size: int) -> bool:
    if kind not in ANALYZABLE_KINDS:
        return False
    if size > MAX_ANALYZABLE_SIZE or size == 0:
        return False
    ext = "." + rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else ""
    if ext in ANALYZABLE_TEXT_EXT_EXCLUDED:
        return False
    return True


async def _select_files_for_analysis(
    project_id: uuid.UUID, limit: int, retry_errors: bool = False
) -> list[ProjectFile]:
    statuses = ["pending", "error"] if retry_errors else ["pending"]
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id,
                ProjectFile.analysis_status.in_(statuses),
            )
        )
        rows = [
            r
            for r in res.scalars()
            if _is_ai_analyzable(r.rel_path, r.kind, r.size)
        ]
    prio = {"config": 0, "code": 1, "test": 2, "doc": 3, "other": 4}
    # pending раньше error: сначала новое, потом ретраи упавших
    rows.sort(
        key=lambda r: (
            0 if r.analysis_status == "pending" else 1,
            prio.get(r.kind, 5),
            r.rel_path.count("/"),
            r.size,
        )
    )
    return rows[:limit]


async def _analyze_batch(project: Project, batch: list[ProjectFile]) -> dict:
    s = get_settings()
    file_list = "\n".join(f"- {f.rel_path} ({f.kind}, {f.size} байт)" for f in batch)
    prompt = FILE_ANALYSIS_PROMPT.format(file_list=file_list)
    obj = meta = None
    for attempt in (1, 2):  # транзиентные сбои claude ретраим один раз
        try:
            obj, meta = await claude_cli.run_json_prompt(
                prompt,
                cwd=project.root_path,
                system=FILE_ANALYSIS_SYSTEM,
                tools=["Read"],
                model=s.ai_model,
                reasoning=s.ai_reasoning,
                timeout=s.claude_timeout_sec,
            )
            break
        except claude_cli.ClaudeError as e:
            log.warning("Батч анализа упал (попытка %d): %s", attempt, e)
            if attempt == 1:
                await asyncio.sleep(2)
    if obj is None:
        async with get_sessionmaker()() as session:
            await session.execute(
                update(ProjectFile)
                .where(ProjectFile.id.in_([f.id for f in batch]))
                .values(analysis_status="error")
            )
            await session.commit()
        return {"analyzed": 0, "errors": len(batch), "cost_usd": 0.0}

    items = obj if isinstance(obj, list) else [obj]
    by_path = {str(i.get("path", "")).replace("\\", "/"): i for i in items if isinstance(i, dict)}
    analyzed = 0
    pid = str(project.id)
    vector_docs: list[dict] = []
    async with get_sessionmaker()() as session:
        for f in batch:
            item = by_path.get(f.rel_path)
            if item is None:
                await session.execute(
                    update(ProjectFile).where(ProjectFile.id == f.id).values(analysis_status="error")
                )
                continue
            summary = str(item.get("summary", ""))[:4000]
            role = str(item.get("role", ""))[:400]
            await graphdb.upsert_file_analysis(pid, f.rel_path, item)
            await session.execute(
                update(ProjectFile)
                .where(ProjectFile.id == f.id)
                .values(
                    analysis_status="analyzed",
                    analyzed_sha256=f.sha256,
                    summary=(role + ". " + summary).strip(". ")[:4000],
                )
            )
            entity_names = ", ".join(
                str(e.get("name", "")) for e in (item.get("entities") or [])[:20] if isinstance(e, dict)
            )
            vector_docs.append(
                {
                    "kind": "file",
                    "key": f.rel_path,
                    "title": f.rel_path,
                    "text": f"{role}. {summary}" + (f"\nСущности: {entity_names}" if entity_names else ""),
                }
            )
            analyzed += 1
        await session.commit()
    await vectors.upsert(pid, vector_docs)
    return {
        "analyzed": analyzed,
        "errors": len(batch) - analyzed,
        "cost_usd": float(meta.get("cost_usd") or 0.0),
    }


async def _run_ai_analysis(
    job_id: uuid.UUID,
    project: Project,
    limit: int,
    base_progress: float,
    span: float,
    retry_errors: bool = False,
) -> dict:
    s = get_settings()
    files = await _select_files_for_analysis(project.id, limit, retry_errors)
    if not files:
        return {"analyzed": 0, "errors": 0, "cost_usd": 0.0, "pending_left": 0}
    batches = [files[i : i + s.ai_batch_size] for i in range(0, len(files), s.ai_batch_size)]
    sem = asyncio.Semaphore(s.ai_concurrency)
    done_count = 0
    totals = {"analyzed": 0, "errors": 0, "cost_usd": 0.0}

    async def run_one(b: list[ProjectFile]) -> None:
        nonlocal done_count
        if runner.is_cancelled(job_id):
            return  # не начинаем новые батчи после запроса отмены
        async with sem:
            r = await _analyze_batch(project, b)
        totals["analyzed"] += r["analyzed"]
        totals["errors"] += r["errors"]
        totals["cost_usd"] += r["cost_usd"]
        done_count += 1
        await runner.report(
            job_id,
            base_progress + span * (done_count / len(batches)),
            f"ИИ-анализ файлов: батч {done_count}/{len(batches)}",
        )

    await asyncio.gather(*(run_one(b) for b in batches))
    runner.check_cancelled(job_id)

    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(ProjectFile.id).where(
                ProjectFile.project_id == project.id, ProjectFile.analysis_status == "pending"
            )
        )
        pending_left = len(res.all())
    totals["pending_left"] = pending_left
    totals["cost_usd"] = round(totals["cost_usd"], 4)
    return totals


async def _run_synthesis(project: Project) -> dict | None:
    s = get_settings()
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(ProjectFile.rel_path, ProjectFile.kind, ProjectFile.summary)
            .where(ProjectFile.project_id == project.id, ProjectFile.summary.is_not(None))
            .limit(250)
        )
        rows = res.all()
    if not rows:
        return None
    summaries = "\n".join(f"- {r.rel_path}: {(r.summary or '')[:160]}" for r in rows)[:16000]
    detect_info = json.dumps(project.meta.get("detect", {}), ensure_ascii=False)
    prompt = SYNTHESIS_PROMPT.format(
        project_name=project.name, detect_info=detect_info, file_summaries=summaries
    )
    try:
        obj, _meta = await claude_cli.run_json_prompt(
            prompt,
            cwd=project.root_path,
            system=SYNTHESIS_SYSTEM,
            tools=["Read", "Glob", "Grep"],
            model=s.ai_model,
            reasoning="medium",
            timeout=s.claude_timeout_sec,
        )
    except claude_cli.ClaudeError as e:
        log.warning("Синтез обзора упал: %s", e)
        return None
    if not isinstance(obj, dict):
        return None
    await graphdb.set_project_overview(str(project.id), obj)
    return obj


async def _file_stats(project_id: uuid.UUID) -> dict:
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(ProjectFile.kind, ProjectFile.analysis_status).where(
                ProjectFile.project_id == project_id
            )
        )
        rows = res.all()
    by_kind: dict[str, int] = {}
    analyzed = 0
    for kind, status in rows:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if status == "analyzed":
            analyzed += 1
    return {"files_total": len(rows), "by_kind": by_kind, "analyzed": analyzed}


async def index_project(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    """Основной пайплайн: скан → diff → граф структуры → ИИ-анализ → синтез."""
    s = get_settings()
    mode = params.get("mode", "update")
    project = await _get_project(project_id)
    await _set_project(project_id, status="indexing")

    try:
        await runner.report(job_id, 0.02, "Сканирование каталога")
        known = await _load_known(project_id)
        force = mode == "reverify"
        scanned = await asyncio.to_thread(scan_directory, project.root_path, known, force)
        diff = diff_scan(scanned, known)
        runner.check_cancelled(job_id)

        await runner.report(job_id, 0.12, "Обновление реестра файлов")
        await _apply_scan_to_db(project_id, diff)
        if diff.deleted:
            await vectors.delete(str(project_id), kind="file", keys=diff.deleted)
        if mode == "reverify":
            async with get_sessionmaker()() as session:
                await session.execute(
                    update(ProjectFile)
                    .where(ProjectFile.project_id == project_id)
                    .values(analysis_status="pending")
                )
                await session.commit()

        await runner.report(job_id, 0.2, "Синхронизация структуры в граф")
        pid = str(project_id)
        detect = await asyncio.to_thread(
            detect_project, project.root_path, [f.rel_path for f in scanned]
        )
        meta = dict(project.meta)
        meta["detect"] = detect
        await graphdb.sync_project_node(pid, project.name, detect)
        await graphdb.sync_structure(pid, _graph_files(scanned), diff.deleted)

        # отчёт об изменениях
        async with get_sessionmaker()() as session:
            session.add(
                ChangeReport(
                    project_id=project_id,
                    job_id=job_id,
                    mode=mode,
                    added=[f.rel_path for f in diff.added][:1000],
                    modified=[f.rel_path for f in diff.modified][:1000],
                    deleted=diff.deleted[:1000],
                    stats=diff.stats,
                )
            )
            await session.commit()

        ai_stats: dict = {"analyzed": 0, "errors": 0, "cost_usd": 0.0, "pending_left": 0}
        overview = None
        raw_limit = params.get("ai_limit")
        limit = s.ai_max_files_per_run if raw_limit is None else int(raw_limit)
        # watch-триггер без реальных изменений (шумовое событие ФС) — ИИ-бюджет не тратим
        watch_noop = params.get("trigger") == "watch" and not (
            diff.added or diff.modified or diff.deleted
        )
        if s.ai_analysis_enabled and params.get("ai", True) and limit > 0 and not watch_noop:
            await runner.report(job_id, 0.25, "ИИ-анализ файлов")
            ai_stats = await _run_ai_analysis(
                job_id, project, limit, 0.25, 0.55, retry_errors=bool(params.get("retry_errors"))
            )
            runner.check_cancelled(job_id)
            if ai_stats["analyzed"] > 0 or not project.meta.get("overview"):
                await runner.report(job_id, 0.85, "Синтез обзора проекта")
                overview = await _run_synthesis(project)

        if overview:
            meta["overview"] = overview
            for key in ("project_kinds", "stack"):
                if overview.get(key):
                    meta.setdefault("detect", {})[key] = overview[key]

        meta["stats"] = await _file_stats(project_id)
        await _set_project(project_id, status="ready", meta=meta)

        # перегенерировать плагин со свежими знаниями
        try:
            from . import plugin_gen

            await plugin_gen.generate_plugin(project_id)
        except Exception:
            log.exception("Не удалось перегенерировать плагин")

        stats: dict = {"scan": diff.stats, "ai": ai_stats, "mode": mode}
        # очередь анализа: пока в бэклоге есть файлы и прогресс идёт — продолжаем сами
        if (
            params.get("auto_continue")
            and s.ai_analysis_enabled
            and params.get("ai", True)
            and limit > 0
            and ai_stats.get("pending_left", 0) > 0
            and ai_stats.get("analyzed", 0) > 0
        ):
            await runner.submit(
                project_id,
                "index",
                {"mode": "update", "ai_limit": limit, "auto_continue": True},
            )
            stats["auto_continued"] = True
            log.info(
                "Автопродолжение анализа %s: в бэклоге осталось %d файлов",
                project_id,
                ai_stats["pending_left"],
            )
        return stats
    except JobCancelled:
        await _set_project(project_id, status="ready")
        raise
    except Exception:
        await _set_project(project_id, status="error")
        raise


async def knowledge_update(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    """Суб-агент актуализации: после log_work/task_done пересканирует изменения,
    дообновляет граф и помечает записи worklog синхронизированными."""
    stats = await index_project(job_id, project_id, {"mode": "update", "ai_limit": params.get("ai_limit", 20)})
    pid = str(project_id)
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(WorkLogEntry).where(
                WorkLogEntry.project_id == project_id, WorkLogEntry.synced.is_(False)
            )
        )
        entries = list(res.scalars())
        for e in entries:
            await graphdb.upsert_worklog_node(pid, str(e.id), e.description, list(e.files or []))
            if e.task_id:
                task = await session.get(TaskItem, e.task_id)
                if task:
                    await graphdb.upsert_task_node(
                        pid, str(task.id), task.title, task.status, list(e.files or [])
                    )
            e.synced = True
        await session.commit()
    stats["worklog_synced"] = len(entries)
    return stats


async def verify_tasks(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    """ИИ-проверка: какие открытые задачи уже реализованы в кодовой базе."""
    s = get_settings()
    project = await _get_project(project_id)
    task_ids = params.get("task_ids")
    async with get_sessionmaker()() as session:
        q = select(TaskItem).where(
            TaskItem.project_id == project_id,
            TaskItem.status.in_(["planned", "in_progress", "review"]),
        )
        if task_ids:
            q = q.where(TaskItem.id.in_([uuid.UUID(t) for t in task_ids]))
        res = await session.execute(q)
        tasks = list(res.scalars())

    if not tasks:
        return {"checked": 0, "done": 0}

    from .decisions import get_decisions_text
    from .rlm import GIT_TOOLS

    context = await graphdb.get_project_summary_context(str(project_id), 3000)
    decisions = await get_decisions_text(project_id)
    sem = asyncio.Semaphore(s.ai_concurrency)
    done_cnt = 0
    partial_cnt = 0
    checked = 0

    async def check(task: TaskItem) -> None:
        nonlocal done_cnt, partial_cnt, checked
        if runner.is_cancelled(job_id):
            return
        prompt = TASK_VERIFY_PROMPT.format(
            project_name=project.name,
            project_context=context,
            decisions=decisions,
            title=task.title,
            description=task.description[:3000],
        )
        async with sem:
            try:
                obj, _ = await claude_cli.run_json_prompt(
                    prompt,
                    cwd=project.root_path,
                    system=TASK_VERIFY_SYSTEM,
                    tools=["Read", "Grep", "Glob", *GIT_TOOLS],
                    model=s.ai_model,
                    reasoning="medium",
                    timeout=s.claude_timeout_sec,
                )
            except claude_cli.ClaudeError as e:
                log.warning("Проверка задачи %s упала: %s", task.id, e)
                return
        checked += 1
        if not isinstance(obj, dict):
            return
        implemented = str(obj.get("implemented", "no"))
        report = str(obj.get("report", ""))[:4000]
        files = [str(f)[:500] for f in (obj.get("files") or [])[:30]]
        async with get_sessionmaker()() as session:
            db_task = await session.get(TaskItem, task.id)
            if db_task is None:
                return
            if implemented == "yes":
                db_task.status = "done"
                db_task.report = f"[ИИ-проверка] Реализовано. {report}\nФайлы: {', '.join(files)}"
                db_task.done_at = utcnow()
                done_cnt += 1
            elif implemented == "partial":
                db_task.report = f"[ИИ-проверка] Частично реализовано. {report}\nФайлы: {', '.join(files)}"
                partial_cnt += 1
            else:
                db_task.report = f"[ИИ-проверка] Не найдено в коде. {report}" if report else db_task.report
            await session.commit()
            await graphdb.upsert_task_node(str(project_id), str(task.id), db_task.title, db_task.status, files)
        await runner.report(job_id, min(0.95, checked / max(1, len(tasks))), f"Проверено задач: {checked}/{len(tasks)}")

    await asyncio.gather(*(check(t) for t in tasks))
    runner.check_cancelled(job_id)
    return {"checked": checked, "done": done_cnt, "partial": partial_cnt, "total": len(tasks)}
