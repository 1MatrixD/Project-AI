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
    """Полнотекстовый поиск по карте знаний проекта: файлы, сущности (классы, функции,
    эндпоинты, модели), компоненты, документы, задачи. Начинай исследование с него."""
    return _fmt(await _get(f"{P}/graph/search", q=query, limit=limit))


@mcp.tool()
async def graph_cypher(query: str) -> str:
    """Read-only Cypher-запрос к графу знаний Neo4j. Узлы: Project, File, Entity,
    Component, Document, Task, WorkLog — все с полем project_id (параметр $pid уже
    передан). Пример: MATCH (f:File {project_id: $pid})-[:DEFINES]->(e:Entity)
    WHERE e.etype='endpoint' RETURN f.path, e.name LIMIT 25"""
    return _fmt(await _post(f"{P}/graph/cypher", {"query": query}))


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
async def request_reindex(mode: str = "update") -> str:
    """Запустить фоновое обновление индекса проекта. mode: update (только изменения)
    или reverify (перепроверить всё)."""
    return _fmt(await _post(f"{P}/index", {"mode": mode}))


def main() -> None:
    if not (TOKEN and PROJECT_ID):
        raise SystemExit("PROJECTAI_TOKEN и PROJECTAI_PROJECT_ID обязательны")
    mcp.run()


if __name__ == "__main__":
    main()
