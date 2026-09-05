from __future__ import annotations

import logging
import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Decision, Project, ProjectFile, TaskItem, WorkLogEntry
from ..security import create_service_token
from .. import i18n
from . import graphdb, vectors

log = logging.getLogger("projectai.copy")

"""Дублирование проекта.

Смысл — получить площадку для экспериментов, не оплачивая заново ИИ-анализ
файлов: копия наследует `analysis_status`/`summary`, поэтому индексатор считает
файлы уже разобранными и не отправляет их в claude повторно.

Копия физически независима от оригинала на всех трёх хранилищах (Postgres,
Neo4j, Qdrant), так что удаление любой из сторон вторую не задевает. Каталог с
кодом на диске остаётся общим: дубль нужен для опытов над самой системой, а не
для правок кода в изоляции — для этого есть git.

Не копируются чаты (несут `claude_session_id` чужой сессии), материалы (их
файлы на диске удалялись бы вместе с оригиналом) и история фоновых задач.
"""

#: ключи meta, которые копии нужны свои
_META_DROP = ("service_token", "watch")


async def _unique_name(session: AsyncSession, owner_id: uuid.UUID, base: str) -> str:
    res = await session.execute(select(Project.name).where(Project.owner_id == owner_id))
    taken = {n for (n,) in res.all()}
    name = i18n._("{base} — копия").format(base=base)
    n = 2
    while name in taken:
        name = i18n._("{base} — копия {n}").format(base=base, n=n)
        n += 1
    # плагин проекта ключуется по слагу имени: одинаковые имена перетирали бы
    # каталог друг друга, поэтому уникальность имени тут не косметика
    return name[:200]


def _remap_extra(extra: dict, id_map: dict[str, str]) -> dict:
    """Ссылки на задачи внутри extra — на новые id. Планировщик хранит там
    depends_on/subtasks/parent_task, и без перемаппинга связи копии указывали бы
    на карточки оригинала."""
    out = dict(extra or {})
    if isinstance(out.get("depends_on"), list):
        out["depends_on"] = [id_map[d] for d in out["depends_on"] if d in id_map]
    if isinstance(out.get("subtasks"), list):
        out["subtasks"] = [id_map[s] for s in out["subtasks"] if s in id_map]
    if out.get("parent_task"):
        out["parent_task"] = id_map.get(str(out["parent_task"]))
    return out


async def duplicate_project(
    session: AsyncSession, project: Project, owner_id: uuid.UUID, name: str | None = None
) -> Project:
    old_pid = str(project.id)

    meta = {k: v for k, v in (project.meta or {}).items() if k not in _META_DROP}
    meta["watch"] = False  # тот же каталог на диске: два наблюдателя задвоили бы индексацию
    meta["duplicated_from"] = old_pid

    copy = Project(
        owner_id=owner_id,
        name=(name or "").strip() or await _unique_name(session, owner_id, project.name),
        description=project.description,
        root_path=project.root_path,
        status=project.status,
        meta=meta,
    )
    session.add(copy)
    await session.flush()  # нужен id для токена и для дочерних строк

    meta["service_token"] = create_service_token(owner_id, copy.id)
    copy.meta = dict(meta)
    new_pid = str(copy.id)

    # --- файлы: главное здесь — перенести analysis_status как есть ---
    res = await session.execute(select(ProjectFile).where(ProjectFile.project_id == project.id))
    rows = [
        {
            "id": uuid.uuid4(),
            "project_id": copy.id,
            "rel_path": f.rel_path,
            "sha256": f.sha256,
            "size": f.size,
            "mtime": f.mtime,
            "kind": f.kind,
            "analysis_status": f.analysis_status,
            "analyzed_sha256": f.analyzed_sha256,
            "summary": f.summary,
        }
        for f in res.scalars()
    ]
    if rows:
        await session.execute(insert(ProjectFile), rows)

    # --- соглашения ---
    res = await session.execute(select(Decision).where(Decision.project_id == project.id))
    for d in res.scalars():
        session.add(
            Decision(project_id=copy.id, topic=d.topic, text=d.text, source=d.source)
        )

    # --- задачи (новые id) и worklog, привязанный к ним ---
    res = await session.execute(
        select(TaskItem).where(TaskItem.project_id == project.id).order_by(TaskItem.created_at)
    )
    old_tasks = list(res.scalars())
    id_map = {str(t.id): str(uuid.uuid4()) for t in old_tasks}
    new_tasks: list[TaskItem] = []
    for t in old_tasks:
        new_tasks.append(
            TaskItem(
                id=uuid.UUID(id_map[str(t.id)]),
                project_id=copy.id,
                title=t.title,
                description=t.description,
                status=t.status,
                source=t.source,
                order=t.order,
                plan=list(t.plan or []),
                extra=_remap_extra(t.extra or {}, id_map),
                report=t.report,
                done_at=t.done_at,
            )
        )
    session.add_all(new_tasks)

    res = await session.execute(
        select(WorkLogEntry).where(WorkLogEntry.project_id == project.id)
    )
    for w in res.scalars():
        mapped = id_map.get(str(w.task_id)) if w.task_id else None
        session.add(
            WorkLogEntry(
                project_id=copy.id,
                task_id=uuid.UUID(mapped) if mapped else None,
                description=w.description,
                files=list(w.files or []),
                synced=w.synced,
            )
        )

    await session.commit()
    await session.refresh(copy)

    # --- карта знаний ---
    graph_stats: dict = {}
    try:
        graph_stats = await graphdb.clone_project_graph(old_pid, new_pid)
        # узлы задач приехали со старыми id внутри uid — пересобираем их из копий
        await graphdb.delete_task_nodes(new_pid)
        for t in new_tasks:
            files = [str(f) for f in (t.extra or {}).get("files", [])][:30]
            await graphdb.upsert_task_node(new_pid, str(t.id), t.title, t.status, files)
        for t in new_tasks:
            extra = t.extra or {}
            if extra.get("depends_on") or extra.get("parent_task"):
                await graphdb.link_task_dependencies(
                    new_pid,
                    str(t.id),
                    list(extra.get("depends_on") or []),
                    extra.get("parent_task"),
                )
        await graphdb.sync_project_node(new_pid, copy.name, copy.meta)
    except Exception as e:
        # граф пересобирается индексацией, а вот файлы и задачи уже скопированы —
        # рушить весь дубль из-за недоступного Neo4j неправильно
        log.warning("Клонирование графа для %s не удалось: %s", new_pid, e)

    vector_points = await vectors.clone(old_pid, new_pid)
    log.info(
        "Дубль %s → %s: файлов %d, задач %d, граф %s, векторов %d",
        old_pid, new_pid, len(rows), len(new_tasks), graph_stats or "—", vector_points,
    )
    return copy
