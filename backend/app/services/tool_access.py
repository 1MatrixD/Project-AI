from __future__ import annotations

"""Разграничение MCP-инструментов по поверхностям.

Поверхности:
- chat   — чат внутри приложения «Проекты ИИ»;
- plugin — внешний Claude Code с установленным плагином проекта.

Группы: «внешние» инструменты работы над проектом (знания, задачи, соглашения, RLM)
и «технические» операции самой системы (реиндекс, git-импорт). Настраивается
per-проект (project.meta.tool_access), по умолчанию у плагина технические выключены.
"""

TOOL_GROUPS: dict[str, list[str]] = {
    "knowledge": [
        "project_overview",
        "graph_search",
        "graph_cypher",
        "component_info",
        "file_info",
        "list_files",
    ],
    "materials": ["list_documents", "read_document"],
    "tasks": [
        "task_list",
        "task_create",
        "task_update",
        "task_move",
        "task_done",
        "task_enrich",
        "task_plan",
        "log_work",
    ],
    "decisions": ["list_decisions", "record_decision"],
    "rlm": ["rlm_query"],
    "admin": ["request_reindex", "git_import"],
}

GROUP_LABELS: dict[str, str] = {
    "knowledge": "Знания: граф, обзор, компоненты, файлы",
    "materials": "Материалы: ТЗ, документы, транскрипты созвонов",
    "tasks": "Задачи: канбан, отчёты, worklog",
    "decisions": "Соглашения проекта",
    "rlm": "RLM-запросы по кодовой базе",
    "admin": "Технические: реиндексация, git-импорт",
}

SURFACES = ("chat", "plugin")

DEFAULT_ACCESS: dict[str, dict[str, bool]] = {
    "chat": {g: True for g in TOOL_GROUPS},
    # внешнему плагину технические операции по умолчанию не даём
    "plugin": {g: (g != "admin") for g in TOOL_GROUPS},
}


def effective_access(meta: dict) -> dict[str, dict[str, bool]]:
    """Настройки проекта поверх дефолтов."""
    stored = meta.get("tool_access") or {}
    out: dict[str, dict[str, bool]] = {}
    for surface in SURFACES:
        surface_stored = stored.get(surface) or {}
        out[surface] = {
            g: bool(surface_stored.get(g, DEFAULT_ACCESS[surface][g])) for g in TOOL_GROUPS
        }
    return out


def allowed_tools_for_surface(meta: dict, surface: str) -> set[str]:
    access = effective_access(meta).get(surface, DEFAULT_ACCESS["plugin"])
    allowed: set[str] = set()
    for group, enabled in access.items():
        if enabled:
            allowed.update(TOOL_GROUPS.get(group, []))
    return allowed
