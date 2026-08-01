from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path

from ..config import BACKEND_ROOT, get_settings
from ..db import get_sessionmaker
from ..models import Project
from ..security import create_service_token

log = logging.getLogger("projectai.plugin")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9а-яё]+", "-", name.lower()).strip("-")
    slug = slug or "project"
    # плагины claude требуют латиницу — транслитерируем кириллицу
    table = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhccss'y'eua",
    )
    return slug.translate(table)[:60]


def _mcp_server_config(project: Project, token: str) -> dict:
    s = get_settings()
    return {
        "command": sys.executable,
        "args": [str(BACKEND_ROOT / "mcp_main.py")],
        "env": {
            "PROJECTAI_API_URL": f"http://localhost:{s.api_port}",
            "PROJECTAI_TOKEN": token,
            "PROJECTAI_PROJECT_ID": str(project.id),
            "PYTHONPATH": str(BACKEND_ROOT),
            "PYTHONIOENCODING": "utf-8",
        },
    }


async def _get_service_token(project_id: uuid.UUID) -> tuple[Project, str]:
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Проект не найден")
        meta = dict(project.meta)
        token = meta.get("service_token")
        if not token:
            token = create_service_token(project.owner_id, project.id)
            meta["service_token"] = token
            project.meta = meta
            await session.commit()
        return project, token


def write_chat_mcp_config(project: Project, token: str) -> str:
    """Конфиг MCP для вызовов claude -p из чата/фонов."""
    s = get_settings()
    d = s.data_path / "mcp"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{project.id}.json"
    config = {"mcpServers": {"projectai": _mcp_server_config(project, token)}}
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


async def get_chat_mcp_config(project_id: uuid.UUID) -> str:
    project, token = await _get_service_token(project_id)
    return write_chat_mcp_config(project, token)


def _skill(name: str, description: str, body: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


async def generate_plugin(project_id: uuid.UUID) -> str:
    """Генерирует устанавливаемый плагин Claude Code для проекта:
    MCP-сервер + скиллы из карты знаний. Возвращает путь плагина."""
    project, token = await _get_service_token(project_id)
    s = get_settings()
    slug = f"projectai-{slugify(project.name)}"
    plugin_dir = s.data_path / "plugins" / slug
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)

    overview = project.meta.get("overview") or {}
    detect = project.meta.get("detect") or {}

    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": slug,
                "description": f"Знания и инструменты проекта «{project.name}» (Проекты ИИ)",
                "version": "0.1.0",
                "author": {"name": "Проекты ИИ"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (plugin_dir / ".mcp.json").write_text(
        json.dumps(
            {"projectai": _mcp_server_config(project, token)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- скиллы из карты знаний ---
    skills_dir = plugin_dir / "skills"

    arch_body_parts = [f"# Архитектура проекта «{project.name}»", ""]
    if overview.get("summary"):
        arch_body_parts += [overview["summary"], ""]
    if detect.get("stack"):
        arch_body_parts += ["## Стек", ", ".join(detect["stack"]), ""]
    for comp in (overview.get("components") or [])[:30]:
        arch_body_parts += [
            f"## {comp.get('name')} ({comp.get('kind', 'module')})",
            comp.get("summary", ""),
            "Ключевые файлы: " + ", ".join(comp.get("paths", [])[:10]),
            "",
        ]
    if overview.get("conventions"):
        arch_body_parts += ["## Конвенции", overview["conventions"], ""]
    how_to = overview.get("how_to") or {}
    if how_to:
        arch_body_parts.append("## Как работать с проектом")
        for k, label in (("run", "Запуск"), ("test", "Тесты"), ("migrate", "Миграции"), ("deploy", "Деплой")):
            if how_to.get(k):
                arch_body_parts.append(f"- **{label}**: {how_to[k]}")
        arch_body_parts.append("")
    arch_body_parts.append(
        "Актуальные детали ищи в карте знаний: инструменты `graph_search`, `graph_cypher`, "
        "`project_overview` MCP-сервера projectai."
    )

    d = skills_dir / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        _skill(
            "architecture",
            f"Архитектура, компоненты и конвенции проекта «{project.name}». Используй при любых вопросах об устройстве проекта.",
            "\n".join(arch_body_parts),
        ),
        encoding="utf-8",
    )

    features = overview.get("business_logic") or []
    if features:
        body = [f"# Бизнес-логика «{project.name}»", ""]
        for f in features[:40]:
            body += [f"## {f.get('name')}", f.get("summary", ""), ""]
        d = skills_dir / "business-logic"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            _skill(
                "business-logic",
                f"Бизнес-фичи проекта «{project.name}»: как они работают с точки зрения продукта и кода.",
                "\n".join(body),
            ),
            encoding="utf-8",
        )

    d = skills_dir / "project-workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        _skill(
            "project-workflow",
            "Рабочий процесс задач проекта: канбан, фиксация сделанного, обновление карты знаний. Используй при работе над задачами.",
            f"""# Рабочий процесс проекта «{project.name}»

Проект подключён к системе «Проекты ИИ» (карта знаний + канбан). Доступны MCP-инструменты сервера `projectai`:

## Перед началом работы
1. `task_list` — посмотри доску задач (planned / in_progress / review / done).
2. `project_overview`, `graph_search` — изучи контекст по карте знаний, не читая весь код.
3. Для больших исследований используй `rlm_query` (рекурсивный анализ под-агентом).

## Во время работы
- Возьми задачу: `task_move` в `in_progress`.
- Новые обнаруженные задачи создавай через `task_create` (с планом).
- Уточняй описания через `task_update`.

## После работы — ОБЯЗАТЕЛЬНО
- `task_done(task_id, report, files)` — пометь задачу выполненной с отчётом и списком изменённых файлов.
- Если работа вне задачи — `log_work(description, files)`.
После этого фоновый суб-агент пересканирует изменения и обновит карту знаний проекта.
""",
        ),
        encoding="utf-8",
    )

    _refresh_marketplace()
    log.info("Плагин перегенерирован: %s", plugin_dir)
    return str(plugin_dir)


def _refresh_marketplace() -> None:
    """Каталог-маркетплейс со всеми плагинами проектов: добавляется в claude один раз."""
    s = get_settings()
    plugins_root = s.data_path / "plugins"
    plugins_root.mkdir(parents=True, exist_ok=True)
    entries = []
    for child in sorted(plugins_root.iterdir()):
        manifest = child / ".claude-plugin" / "plugin.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                entries.append(
                    {
                        "name": data["name"],
                        "source": f"./{child.name}",
                        "description": data.get("description", ""),
                    }
                )
            except (OSError, json.JSONDecodeError, KeyError):
                continue
    mp_dir = plugins_root / ".claude-plugin"
    mp_dir.mkdir(parents=True, exist_ok=True)
    (mp_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "projectai",
                "owner": {"name": "Проекты ИИ"},
                "plugins": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def plugin_generate_job(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    path = await generate_plugin(project_id)
    return {"plugin_path": path}


def plugin_install_info(project: Project) -> dict:
    s = get_settings()
    slug = f"projectai-{slugify(project.name)}"
    plugin_dir = s.data_path / "plugins" / slug
    marketplace_dir = s.data_path / "plugins"
    return {
        "slug": slug,
        "path": str(plugin_dir),
        "exists": plugin_dir.is_dir(),
        "marketplace_path": str(marketplace_dir),
        "install_commands": [
            f"claude plugin marketplace add {marketplace_dir}",
            f"claude plugin install {slug}@projectai",
        ],
    }
