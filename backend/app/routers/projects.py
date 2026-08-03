from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_user, get_project
from ..jobs_runner import runner
from ..models import ChangeReport, Project, User
from ..schemas import (
    AskIn,
    AskOut,
    ChangeReportOut,
    IndexRequest,
    ProjectCreate,
    ProjectDetailOut,
    ProjectOut,
    ProjectUpdate,
)
from ..security import create_service_token
from ..services import graphdb, plugin_gen, project_copy, rlm, vectors

log = logging.getLogger("projectai.api.projects")

router = APIRouter(prefix="/projects", tags=["projects"])

INDEX_JOB_TYPES = ["index", "knowledge_update"]


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[ProjectOut]:
    res = await session.execute(
        select(Project).where(Project.owner_id == user.id).order_by(desc(Project.updated_at))
    )
    return [ProjectOut.model_validate(p) for p in res.scalars()]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    root = Path(data.root_path)
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Каталог не найден: {data.root_path}")
    project = Project(
        owner_id=user.id,
        name=data.name.strip(),
        description=data.description.strip(),
        root_path=str(root.resolve()),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    # сервисный токен для MCP/плагина
    project.meta = {"service_token": create_service_token(user.id, project.id)}
    await session.commit()
    await session.refresh(project)

    # сразу запускаем первичную индексацию в фоне
    await runner.submit(project.id, "index", {"mode": "initial"})
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetailOut)
async def get_project_detail(project: Project = Depends(get_project)) -> ProjectDetailOut:
    out = ProjectDetailOut.model_validate(project)
    # сервисный токен наружу не отдаём
    meta = dict(out.meta)
    meta.pop("service_token", None)
    out.meta = meta
    try:
        out.stats = await graphdb.get_stats(str(project.id))
    except Exception as e:
        log.warning("Статистика графа недоступна: %s", e)
        out.stats = {}
    return out


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    data: ProjectUpdate,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    db_project = await session.get(Project, project.id)
    if data.name is not None:
        db_project.name = data.name.strip()
    if data.description is not None:
        db_project.description = data.description.strip()
    await session.commit()
    await session.refresh(db_project)
    return ProjectOut.model_validate(db_project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_session)
) -> None:
    """Удаляет проект целиком: граф, вектора, строку в БД (каскадом — задачи,
    чаты, материалы, worklog) и файлы на диске. Каталог с кодом не трогает."""
    from ..services.watcher import watcher

    # первым делом снимаем наблюдение: иначе watcher продолжит слать индексацию
    # по уже удалённому проекту
    watcher.stop_watch(project.id)
    await graphdb.delete_project_graph(str(project.id))
    await vectors.delete(str(project.id))
    await session.execute(delete(Project).where(Project.id == project.id))
    await session.commit()
    shutil.rmtree(get_settings().data_path / "materials" / str(project.id), ignore_errors=True)
    plugin_gen.remove_project_artifacts(project)


@router.post("/{project_id}/duplicate", response_model=ProjectOut, status_code=201)
async def duplicate_project_endpoint(
    body: dict | None = None,
    project: Project = Depends(get_project),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    """Копия проекта со всей картой знаний — чтобы экспериментировать, не ожидая
    и не оплачивая повторный ИИ-анализ файлов.

    Копия независима: свои строки в БД, свой подграф Neo4j, свои точки Qdrant,
    свой сервисный токен. Удаление оригинала её не заденет. Каталог с кодом
    остаётся общим, наблюдение за ним у копии выключено.
    """
    if await runner.has_active(project.id, INDEX_JOB_TYPES):
        raise HTTPException(
            status_code=409, detail="Идёт индексация — дубль получился бы половинчатым"
        )
    copy = await project_copy.duplicate_project(
        session, project, user.id, str((body or {}).get("name") or "")
    )
    return ProjectOut.model_validate(copy)


@router.post("/{project_id}/index")
async def start_index(
    data: IndexRequest, project: Project = Depends(get_project)
) -> dict:
    if data.mode not in ("initial", "update", "reverify"):
        raise HTTPException(status_code=400, detail="mode: initial | update | reverify")
    if await runner.has_active(project.id, ["index"]):
        raise HTTPException(status_code=409, detail="Индексация уже идёт")
    params: dict = {"mode": data.mode}
    if data.ai_limit is not None:
        params["ai_limit"] = max(0, min(500, data.ai_limit))
    if data.auto_continue:
        params["auto_continue"] = True
    if data.retry_errors:
        params["retry_errors"] = True
    job = await runner.submit(project.id, "index", params)
    return {"job_id": str(job.id), "status": job.status}


@router.post("/{project_id}/watch")
async def set_watch(
    body: dict,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Наблюдение за каталогами проекта: изменения в коде автоматически запускают
    инкрементальное обновление индекса (с дебаунсом). Состояние переживает
    рестарт сервера (meta.watch)."""
    from ..services.roots import get_roots
    from ..services.watcher import watcher

    enabled = bool(body.get("enabled"))
    if enabled:
        try:
            watcher.start_watch(project.id, [r for _a, r in get_roots(project)])
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Наблюдение не запустилось: {e}")
    else:
        watcher.stop_watch(project.id)
    db_project = await session.get(Project, project.id)
    meta = dict(db_project.meta)
    meta["watch"] = enabled
    db_project.meta = meta
    await session.commit()
    return {"watch": enabled}


@router.post("/{project_id}/roots")
async def add_root(
    body: dict,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Мультирепо: добавить каталог к проекту. Его файлы получают префикс
    «алиас/» и попадают в общий индекс/граф/поиск. Сразу запускается
    инкрементальная индексация."""
    from ..services.roots import extra_roots, get_roots, make_alias
    from ..services.watcher import watcher

    raw = str(body.get("path", "")).strip()
    root = Path(raw)
    if not raw or not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Каталог не найден: {raw}")
    path = str(root.resolve())
    db_project = await session.get(Project, project.id)
    existing = {str(Path(p).resolve()) for _a, p in get_roots(db_project)}
    if path in existing:
        raise HTTPException(status_code=409, detail="Этот каталог уже в проекте")
    alias = make_alias(path, db_project)
    meta = dict(db_project.meta)
    meta["extra_roots"] = [*extra_roots(meta), {"alias": alias, "path": path}]
    db_project.meta = meta
    await session.commit()
    await session.refresh(db_project)

    if watcher.is_watching(project.id):
        try:
            watcher.restart_watch(project.id, [r for _a, r in get_roots(db_project)])
        except Exception as e:
            log.warning("Watch не перезапустился после добавления корня: %s", e)

    job_id = None
    if not await runner.has_active(project.id, ["index"]):
        job = await runner.submit(project.id, "index", {"mode": "update"})
        job_id = str(job.id)
    return {"alias": alias, "path": path, "extra_roots": meta["extra_roots"], "job_id": job_id}


@router.delete("/{project_id}/roots/{alias}")
async def remove_root(
    alias: str,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Убрать дополнительный каталог: его файлы удаляются из реестра,
    графа и векторного индекса."""
    from sqlalchemy import delete as sa_delete

    from ..models import ProjectFile
    from ..services.roots import extra_roots, get_roots
    from ..services.watcher import watcher

    roots_list = extra_roots(project.meta)
    if alias not in {r["alias"] for r in roots_list}:
        raise HTTPException(status_code=404, detail=f"Каталог «{alias}» не найден в проекте")

    db_project = await session.get(Project, project.id)
    meta = dict(db_project.meta)
    meta["extra_roots"] = [r for r in roots_list if r["alias"] != alias]
    db_project.meta = meta
    await session.execute(
        sa_delete(ProjectFile).where(
            ProjectFile.project_id == project.id,
            ProjectFile.rel_path.like(alias + "/%"),
        )
    )
    await session.commit()
    await session.refresh(db_project)

    try:
        await graphdb.delete_path_prefix(str(project.id), alias)
    except Exception as e:
        log.warning("Очистка графа по «%s/» не удалась: %s", alias, e)
    await vectors.delete(str(project.id), root=alias)

    if watcher.is_watching(project.id):
        try:
            watcher.restart_watch(project.id, [r for _a, r in get_roots(db_project)])
        except Exception as e:
            log.warning("Watch не перезапустился после удаления корня: %s", e)
    return {"extra_roots": meta["extra_roots"]}


@router.get("/{project_id}/changes", response_model=list[ChangeReportOut])
async def list_changes(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_session)
) -> list[ChangeReportOut]:
    res = await session.execute(
        select(ChangeReport)
        .where(ChangeReport.project_id == project.id)
        .order_by(desc(ChangeReport.created_at))
        .limit(20)
    )
    return [ChangeReportOut.model_validate(r) for r in res.scalars()]


@router.get("/{project_id}/graph")
async def graph_view(project: Project = Depends(get_project), limit: int = 400) -> dict:
    return await graphdb.get_graph_view(str(project.id), min(limit, 1500))


@router.get("/{project_id}/graph/search")
async def graph_search(
    q: str, project: Project = Depends(get_project), limit: int = 15
) -> list[dict]:
    """Гибридный поиск по знаниям: fulltext по графу Neo4j + семантика (Qdrant).

    Каждый хит несёт match: fulltext | semantic | both. Семантика находит
    смысловые совпадения без точного вхождения слов (эмбеддинги)."""
    pid = str(project.id)
    limit = min(limit, 50)
    fulltext: list[dict] = []
    ft_error: Exception | None = None
    try:
        fulltext = await graphdb.fulltext_search(pid, q, limit)
    except Exception as e:
        ft_error = e
        log.warning("Fulltext-поиск упал, остаётся семантика: %s", e)
    semantic = await vectors.search(pid, q, limit=limit)
    if ft_error is not None and not semantic:
        raise HTTPException(status_code=502, detail=f"Поиск по графу недоступен: {ft_error}")

    out: list[dict] = []
    seen: dict[str, dict] = {}
    for hit in fulltext:
        hit["match"] = "fulltext"
        ident = str(hit.get("path") or hit.get("title") or hit.get("name") or id(hit))
        seen[ident] = hit
        out.append(hit)
    for sh in semantic:
        ident = sh["key"] if sh["kind"] == "file" else sh["title"]
        if ident in seen:
            seen[ident]["match"] = "both"
            continue
        shaped: dict = {
            "labels": [vectors.KIND_LABELS.get(sh["kind"], sh["kind"])],
            "score": sh["score"],
            "summary": sh["text"],
            "match": "semantic",
        }
        if sh["kind"] == "file":
            shaped["path"] = sh["key"]
            shaped["name"] = sh["key"].rsplit("/", 1)[-1]
        else:
            shaped["title"] = sh["title"]
        out.append(shaped)
    return out[: limit + 10]


@router.get("/{project_id}/graph/component")
async def graph_component(name: str, project: Project = Depends(get_project)) -> dict:
    info = await graphdb.get_component_info(str(project.id), name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Компонент «{name}» не найден в карте знаний")
    return info


@router.get("/{project_id}/graph/file")
async def graph_file(path: str, project: Project = Depends(get_project)) -> dict:
    info = await graphdb.get_file_info(str(project.id), path)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Файл «{path}» не найден в карте знаний")
    return info


@router.post("/{project_id}/graph/cypher")
async def graph_cypher(
    body: dict, project: Project = Depends(get_project)
) -> list[dict]:
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="Пустой запрос")
    try:
        return await graphdb.run_readonly_cypher(str(project.id), query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Cypher: {e}")


@router.post("/{project_id}/ask", response_model=AskOut)
async def ask(data: AskIn, project: Project = Depends(get_project)) -> AskOut:
    """RLM-вопрос по проекту: рекурсивный анализ без чата."""
    try:
        result = await rlm.answer(project, data.question, data.paths)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RLM-запрос не удался: {e}")
    return AskOut(**result)


@router.get("/{project_id}/export/markdown")
async def export_markdown_endpoint(project: Project = Depends(get_project)):
    """Дамп карты знаний в markdown — для людей и внешних инструментов."""
    from fastapi.responses import Response

    from ..services.export import export_markdown

    content = await export_markdown(project)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="knowledge-map.md"'},
    )


@router.get("/{project_id}/tool-access")
async def get_tool_access(
    project: Project = Depends(get_project), surface: str | None = None
) -> dict:
    """Разграничение MCP-инструментов: chat (чат приложения) / plugin (внешний Claude Code)."""
    from ..services.tool_access import (
        GROUP_LABELS,
        TOOL_GROUPS,
        allowed_tools_for_surface,
        effective_access,
    )

    result: dict = {
        "access": effective_access(project.meta),
        "groups": TOOL_GROUPS,
        "labels": GROUP_LABELS,
    }
    if surface:
        result["allowed_tools"] = sorted(allowed_tools_for_surface(project.meta, surface))
    return result


@router.put("/{project_id}/tool-access")
async def put_tool_access(
    body: dict,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from ..services.tool_access import SURFACES, TOOL_GROUPS, effective_access

    db_project = await session.get(Project, project.id)
    clean: dict = {}
    for surface in SURFACES:
        incoming = (body.get(surface) or {}) if isinstance(body, dict) else {}
        clean[surface] = {g: bool(incoming.get(g, True)) for g in TOOL_GROUPS if g in incoming}
    meta = dict(db_project.meta)
    meta["tool_access"] = clean
    db_project.meta = meta
    await session.commit()
    return {"access": effective_access(meta)}


@router.get("/{project_id}/git/repos")
async def git_repos(project: Project = Depends(get_project)) -> list[dict]:
    """Найденные git-репозитории проекта (включая вложенные) с ветками —
    для настройки импорта per-репозиторий."""
    import asyncio

    from ..services.git_import import find_git_repos, repo_info
    from ..services.roots import get_roots

    out: list[dict] = []
    for alias, root in get_roots(project):
        repos = await asyncio.to_thread(find_git_repos, root)
        infos = await asyncio.gather(
            *[asyncio.to_thread(repo_info, r, root) for r in repos]
        )
        for info in infos:
            if alias:
                info["path"] = alias if info["path"] == "." else f"{alias}/{info['path']}"
            out.append(info)
    return out


@router.post("/{project_id}/git/import")
async def git_import_endpoint(
    body: dict | None = None, project: Project = Depends(get_project)
) -> dict:
    """Импорт истории git (включая вложенные репо) в канбан.

    body: {since_days: 30|null (null = вся история), per_repo_limit: 150}.
    Уже импортированные коммиты пропускаются автоматически.
    """
    if await runner.has_active(project.id, ["git_import"]):
        raise HTTPException(status_code=409, detail="Импорт git уже идёт")
    body = body or {}
    params: dict = {}
    if body.get("since_days"):
        params["since_days"] = max(1, min(3650, int(body["since_days"])))
    if body.get("per_repo_limit"):
        params["per_repo_limit"] = max(1, min(1000, int(body["per_repo_limit"])))
    if isinstance(body.get("repos"), list):
        # per-repo конфиги: [{path, branch?, since_days?, limit?}]
        params["repos"] = [
            {
                "path": str(rc.get("path", ""))[:500],
                "branch": str(rc["branch"])[:100] if rc.get("branch") else None,
                "since_days": max(1, min(3650, int(rc["since_days"]))) if rc.get("since_days") else None,
                "limit": max(1, min(1000, int(rc.get("limit", 150)))),
            }
            for rc in body["repos"]
            if isinstance(rc, dict) and rc.get("path")
        ][:20]
        if not params["repos"]:
            raise HTTPException(status_code=400, detail="Не выбран ни один репозиторий")
    job = await runner.submit(project.id, "git_import", params)
    return {"job_id": str(job.id)}


@router.get("/{project_id}/plugin")
async def plugin_info(project: Project = Depends(get_project)) -> dict:
    return plugin_gen.plugin_install_info(project)


@router.get("/{project_id}/plugin/files")
async def plugin_files(project: Project = Depends(get_project)) -> list[dict]:
    """Файлы сгенерированного плагина (для просмотра скиллов в UI)."""
    info = plugin_gen.plugin_install_info(project)
    root = Path(info["path"])
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append(
                {"path": str(p.relative_to(root)).replace("\\", "/"), "size": p.stat().st_size}
            )
    return out


@router.get("/{project_id}/plugin/file")
async def plugin_file(path: str, project: Project = Depends(get_project)) -> dict:
    info = plugin_gen.plugin_install_info(project)
    root = Path(info["path"]).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise HTTPException(status_code=415, detail="Файл не читается как текст")
    return {"path": path, "content": content[:200_000]}


@router.post("/{project_id}/plugin/regenerate")
async def plugin_regenerate(project: Project = Depends(get_project)) -> dict:
    job = await runner.submit(project.id, "plugin_generate", {})
    return {"job_id": str(job.id)}


@router.post("/{project_id}/plugin/local")
async def plugin_install_local(project: Project = Depends(get_project)) -> dict:
    """Включить плагин только в этом проекте — через
    `<каталог проекта>/.claude/settings.local.json`, а не глобально в ~/.claude."""
    if not Path(project.root_path).is_dir():
        raise HTTPException(status_code=400, detail=f"Каталог проекта не найден: {project.root_path}")
    try:
        return plugin_gen.install_locally(project)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{project_id}/plugin/local")
async def plugin_uninstall_local(project: Project = Depends(get_project)) -> dict:
    try:
        return plugin_gen.uninstall_locally(project)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
