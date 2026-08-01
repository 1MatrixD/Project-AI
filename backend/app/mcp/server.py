"""MCP-сервер «Проекты ИИ» для одного проекта.

Запускается Claude Code (из чата системы или из установленного плагина).
Работает через HTTP API бэкенда с сервисным токеном — единственный источник истины.

Env: PROJECTAI_API_URL, PROJECTAI_TOKEN, PROJECTAI_PROJECT_ID.
"""

from __future__ import annotations

import json
import os

import httpx

try:  # mcp SDK 2.x
    from mcp.server import MCPServer
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

API_URL = os.environ.get("PROJECTAI_API_URL", "http://localhost:8010").rstrip("/")
TOKEN = os.environ.get("PROJECTAI_TOKEN", "")
PROJECT_ID = os.environ.get("PROJECTAI_PROJECT_ID", "")
# chat — чат приложения; plugin — внешний Claude Code (технические инструменты
# по умолчанию отключены, настраивается на вкладке «Плагин»)
SURFACE = os.environ.get("PROJECTAI_SURFACE", "plugin")

mcp = MCPServer(
    "projectai",
    instructions=(
        "Инструменты проекта в системе «Проекты ИИ»: карта знаний (Neo4j), материалы "
        "(транскрипты созвонов, ТЗ), канбан-доска задач, RLM-запросы по кодовой базе. "
        "После выполнения работы обязательно вызывай task_done или log_work — это "
        "запускает суб-агента, который обновляет карту знаний."
    ),
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{API_URL}/api",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=httpx.Timeout(120.0, read=900.0),
    )


async def _get(path: str, **params) -> object:
    async with _client() as c:
        r = await c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()


async def _post(path: str, payload: dict | None = None) -> object:
    async with _client() as c:
        r = await c.post(path, json=payload or {})
        r.raise_for_status()
        return r.json()


async def _patch(path: str, payload: dict) -> object:
    async with _client() as c:
        r = await c.patch(path, json=payload)
        r.raise_for_status()
        return r.json()


def _fmt(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


P = f"/projects/{PROJECT_ID}"


@mcp.tool()
async def project_overview() -> str:
    """Обзор проекта: описание, стек, компоненты, статистика карты знаний."""
    data = await _get(P)
    keep = {k: data.get(k) for k in ("name", "description", "status", "meta", "stats")}
    return _fmt(keep)


@mcp.tool()
async def graph_search(query: str, limit: int = 15) -> str:
    """Гибридный поиск по карте знаний: полнотекстовый (Neo4j) + семантический
    (эмбеддинги, Qdrant) — находит и точные вхождения, и смысловые совпадения
    другими словами. Файлы, сущности, компоненты, документы, задачи, соглашения.
    Начинай исследование с него. Поле match: fulltext | semantic | both."""
    return _fmt(await _get(f"{P}/graph/search", q=query, limit=limit))


@mcp.tool()
async def graph_cypher(query: str) -> str:
    """Read-only Cypher-запрос к графу знаний Neo4j. Узлы: Project, File, Entity,
    Component, Document, Task, WorkLog — все с полем project_id (параметр $pid уже
    передан). Пример: MATCH (f:File {project_id: $pid})-[:DEFINES]->(e:Entity)
    WHERE e.etype='endpoint' RETURN f.path, e.name LIMIT 25"""
    return _fmt(await _post(f"{P}/graph/cypher", {"query": query}))


@mcp.tool()
async def component_info(name: str) -> str:
    """Детали компонента/сервиса из карты знаний: описание, за что отвечает,
    ключевые файлы с ролями. name — часть имени (например «admin-backend»)."""
    return _fmt(await _get(f"{P}/graph/component", name=name))


@mcp.tool()
async def file_info(path: str) -> str:
    """Досье файла из карты знаний: роль, сущности, связи с другими файлами,
    задачи и работы, которые его касались. path — относительно корня проекта."""
    return _fmt(await _get(f"{P}/graph/file", path=path))


@mcp.tool()
async def list_decisions() -> str:
    """Соглашения проекта: актуальные решения и смены подходов («раньше X, теперь Y»).
    Код, противоречащий соглашению, — легаси, а не эталон. Сверяйся перед тем,
    как назвать что-то багом."""
    return _fmt(await _get(f"{P}/decisions"))


@mcp.tool()
async def record_decision(topic: str, text: str) -> str:
    """Зафиксировать соглашение/решение проекта. ОБЯЗАТЕЛЬНО вызывай, когда
    пользователь поправляет понимание проекта («это не баг, мы сменили подход»)
    или на созвоне зафиксирована смена подхода. Совпадающая тема обновляется."""
    return _fmt(await _post(f"{P}/decisions", {"topic": topic, "text": text}))


@mcp.tool()
async def git_import() -> str:
    """Импортировать историю git (включая вложенные репо монорепо) в канбан:
    коммиты группируются в выполненные работы, совпадающие открытые задачи
    закрываются с отчётом. Выполняется в фоне."""
    return _fmt(await _post(f"{P}/git/import"))


@mcp.tool()
async def list_files(query: str = "", kind: str = "", limit: int = 50) -> str:
    """Реестр файлов проекта с ролями и сводками. kind: code|config|doc|test|asset|data|other."""
    return _fmt(await _get(f"{P}/files", q=query or None, kind=kind or None, limit=limit))


@mcp.tool()
async def list_documents() -> str:
    """Материалы проекта: транскрипты созвонов, ТЗ, документы — со статусами и выжимками."""
    return _fmt(await _get(f"{P}/materials"))


@mcp.tool()
async def read_document(material_id: str, offset: int = 0, limit_chars: int = 20000) -> str:
    """Прочитать текст материала (транскрипт/документ) по id из list_documents."""
    data = await _get(f"{P}/materials/{material_id}/text", offset=offset, limit_chars=limit_chars)
    return data.get("text", "") if isinstance(data, dict) else str(data)


@mcp.tool()
async def rlm_query(question: str, paths: list[str] | None = None) -> str:
    """Рекурсивный анализ кодовой базы (паттерн RLM): под-агент прочитает файлы и ответит,
    не засоряя твой контекст. Передай paths (списком до 30 файлов) для точного скоупа,
    либо оставь пустым — система сама спланирует группы файлов по карте знаний."""
    data = await _post(f"{P}/ask", {"question": question, "paths": paths})
    return data.get("answer", "") if isinstance(data, dict) else str(data)


# --- канбан ---

@mcp.tool()
async def task_list(status: str = "") -> str:
    """Канбан-доска задач проекта. status: planned|in_progress|review|done|cancelled (пусто = все)."""
    return _fmt(await _get(f"{P}/tasks", status=status or None))


@mcp.tool()
async def task_create(title: str, description: str = "", plan: list[str] | None = None) -> str:
    """Создать задачу в канбане (колонка «Запланировано»). plan — список шагов."""
    return _fmt(await _post(f"{P}/tasks", {"title": title, "description": description, "source": "chat", "plan": plan or []}))


@mcp.tool()
async def task_update(task_id: str, title: str | None = None, description: str | None = None, plan: list[str] | None = None) -> str:
    """Улучшить/уточнить задачу: название, описание, план."""
    payload = {k: v for k, v in (("title", title), ("description", description), ("plan", plan)) if v is not None}
    return _fmt(await _patch(f"{P}/tasks/{task_id}", payload))


@mcp.tool()
async def task_move(task_id: str, status: str) -> str:
    """Переместить задачу в колонку: planned | in_progress | review | done | cancelled."""
    return _fmt(await _patch(f"{P}/tasks/{task_id}", {"status": status}))


@mcp.tool()
async def task_done(task_id: str, report: str, files: list[str] | None = None) -> str:
    """Пометить задачу выполненной: отчёт «что сделано» + изменённые файлы.
    Запускает суб-агента обновления карты знаний."""
    return _fmt(await _post(f"{P}/tasks/{task_id}/done", {"report": report, "files": files or []}))


@mcp.tool()
async def log_work(description: str, files: list[str] | None = None, task_id: str | None = None) -> str:
    """Зафиксировать сделанную работу вне задачи (или добавочно к задаче).
    Запускает суб-агента обновления карты знаний."""
    payload: dict = {"description": description, "files": files or []}
    if task_id:
        payload["task_id"] = task_id
    return _fmt(await _post(f"{P}/worklog", payload))


@mcp.tool()
async def task_enrich(task_id: str | None = None) -> str:
    """RLM-проработка задач: короткая формулировка → детальная задача со ссылками
    на файлы, планом-чеклистом и связями с существующими задачами. Без task_id
    прорабатываются все новые задачи. Выполняется в фоне."""
    if task_id:
        return _fmt(await _post(f"{P}/tasks/{task_id}/enrich"))
    return _fmt(await _post(f"{P}/tasks/enrich", {}))


@mcp.tool()
async def task_plan(task_id: str) -> str:
    """Планировщик: ИИ исследует кодовую базу, строит общий план и разбивает крупную
    задачу на подзадачи канбана с зависимостями (что за чем делать; независимые —
    параллельно). Выполняется в фоне."""
    return _fmt(await _post(f"{P}/tasks/{task_id}/plan"))


@mcp.tool()
async def request_reindex(mode: str = "update") -> str:
    """Запустить фоновое обновление индекса проекта. mode: update (только изменения)
    или reverify (перепроверить всё)."""
    return _fmt(await _post(f"{P}/index", {"mode": mode}))


def _apply_tool_access() -> None:
    """Скрывает инструменты, выключенные для этой поверхности в настройках проекта."""
    try:
        with httpx.Client(
            base_url=f"{API_URL}/api",
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=10.0,
        ) as c:
            r = c.get(f"{P}/tool-access", params={"surface": SURFACE})
            r.raise_for_status()
            allowed = set(r.json().get("allowed_tools") or [])
    except Exception:
        return  # API недоступен — оставляем все инструменты (границу решает бэкенд)
    if not allowed:
        return
    for tool_name in [
        "project_overview", "graph_search", "graph_cypher", "component_info", "file_info",
        "list_files", "list_documents", "read_document", "rlm_query", "task_list",
        "task_create", "task_update", "task_move", "task_done", "task_enrich", "task_plan", "log_work",
        "list_decisions", "record_decision", "request_reindex", "git_import",
    ]:
        if tool_name not in allowed:
            try:
                mcp.remove_tool(tool_name)
            except Exception:
                pass


def main() -> None:
    if not (TOKEN and PROJECT_ID):
        raise SystemExit("PROJECTAI_TOKEN и PROJECTAI_PROJECT_ID обязательны")
    _apply_tool_access()
    mcp.run()


if __name__ == "__main__":
    main()
