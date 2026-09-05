from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path

from ..config import BACKEND_ROOT, get_settings
from ..db import get_sessionmaker
from .. import i18n
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


def plugin_slug(project: Project) -> str:
    """Каталог плагина ключуется по имени, а не по id — значит, у двух проектов
    с одинаковым именем он общий. Дубль обязан получить другое имя."""
    return f"projectai-{slugify(project.name)}"


def _mcp_server_config(project: Project, token: str, surface: str = "plugin") -> dict:
    s = get_settings()
    return {
        "command": sys.executable,
        "args": [str(BACKEND_ROOT / "mcp_main.py")],
        "env": {
            "PROJECTAI_API_URL": f"http://localhost:{s.api_port}",
            "PROJECTAI_TOKEN": token,
            "PROJECTAI_PROJECT_ID": str(project.id),
            "PROJECTAI_SURFACE": surface,
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
    config = {"mcpServers": {"projectai": _mcp_server_config(project, token, surface="chat")}}
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
    slug = plugin_slug(project)
    plugin_dir = s.data_path / "plugins" / slug
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)

    overview = project.meta.get("overview") or {}
    detect = project.meta.get("detect") or {}

    from sqlalchemy import select

    from ..models import Decision

    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(Decision)
            .where(Decision.project_id == project.id)
            .order_by(Decision.updated_at.desc())
            .limit(60)
        )
        decisions = list(res.scalars())

    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": slug,
                "description": i18n._("Знания и инструменты проекта «{name}» (Проекты ИИ)").format(name=project.name),
                "version": "0.1.0",
                "author": {"name": i18n._("Проекты ИИ")},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (plugin_dir / ".mcp.json").write_text(
        json.dumps(
            {"projectai": _mcp_server_config(project, token, surface="plugin")},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- скиллы из карты знаний ---
    skills_dir = plugin_dir / "skills"

    arch_body_parts = [i18n._("# Архитектура проекта «{name}»").format(name=project.name), ""]
    if overview.get("summary"):
        arch_body_parts += [overview["summary"], ""]
    if detect.get("stack"):
        arch_body_parts += [i18n._("## Стек"), ", ".join(detect["stack"]), ""]
    for comp in (overview.get("components") or [])[:30]:
        arch_body_parts += [
            f"## {comp.get('name')} ({comp.get('kind', 'module')})",
            comp.get("summary", ""),
            i18n._("Ключевые файлы: ") + ", ".join(comp.get("paths", [])[:10]),
            "",
        ]
    if overview.get("conventions"):
        arch_body_parts += [i18n._("## Конвенции"), overview["conventions"], ""]
    if decisions:
        arch_body_parts.append(i18n._("## Соглашения и актуальные решения"))
        arch_body_parts.append(
            i18n._("Код, противоречащий этим решениям, — легаси, а не эталон. Актуальный список — `list_decisions`.")
        )
        for d in decisions[:40]:
            arch_body_parts.append(f"- **{d.topic}**: {d.text[:600]}")
        arch_body_parts.append("")
    how_to = overview.get("how_to") or {}
    if how_to:
        arch_body_parts.append(i18n._("## Как работать с проектом"))
        for k, label in (("run", "Запуск"), ("test", "Тесты"), ("migrate", "Миграции"), ("deploy", "Деплой")):
            if how_to.get(k):
                arch_body_parts.append(f"- **{i18n._(label)}**: {how_to[k]}")
        arch_body_parts.append("")
    arch_body_parts.append(
        i18n._("Актуальные детали ищи в карте знаний: инструменты `graph_search`, `graph_cypher`, `project_overview` MCP-сервера projectai.")
    )

    d = skills_dir / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        _skill(
            "architecture",
            i18n._("Архитектура, компоненты и конвенции проекта «{name}». Используй при любых вопросах об устройстве проекта.").format(name=project.name),
            "\n".join(arch_body_parts),
        ),
        encoding="utf-8",
    )

    # скилл «сервисы»: какие компоненты есть и за что отвечают, с файлами
    comps = overview.get("components") or []
    if comps:
        body = [
            i18n._("# Сервисы и компоненты «{name}»").format(name=project.name),
            "",
            i18n._("За деталями по компоненту — MCP `component_info(name)`; по файлу — `file_info(path)`."),
            "",
        ]
        for c in comps[:40]:
            body += [
                f"## {c.get('name')} ({c.get('kind', 'module')})",
                c.get("summary", ""),
                i18n._("Ключевые файлы: ") + ", ".join(c.get("paths", [])[:12]),
                "",
            ]
        d = skills_dir / "services"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            _skill(
                "services",
                i18n._("Сервисы и компоненты проекта «{name}»: за что каждый отвечает, ключевые файлы. Используй при вопросах «где реализовано X».").format(name=project.name),
                "\n".join(body),
            ),
            encoding="utf-8",
        )

    features = overview.get("business_logic") or []
    if features:
        body = [i18n._("# Бизнес-логика «{name}»").format(name=project.name), ""]
        for f in features[:40]:
            body += [f"## {f.get('name')}", f.get("summary", ""), ""]
        d = skills_dir / "business-logic"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            _skill(
                "business-logic",
                i18n._("Бизнес-фичи проекта «{name}»: как они работают с точки зрения продукта и кода.").format(name=project.name),
                "\n".join(body),
            ),
            encoding="utf-8",
        )

    d = skills_dir / "project-workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        _skill(
            "project-workflow",
            i18n._("Рабочий процесс задач проекта: канбан, фиксация сделанного и решений, обновление карты знаний. Используй при работе над задачами."),
            i18n.text("skill_workflow_body").format(name=project.name),
        ),
        encoding="utf-8",
    )

    # сценарные скиллы: не срез карты, а «как добиться X» — без них агент выбирает
    # инструменты вслепую по их описаниям
    d = skills_dir / "task-briefing"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        _skill(
            "task-briefing",
            i18n._("Разбор тяжёлой или мутно сформулированной задачи: RLM-досье — где смотреть, нюансы, как проверить. Используй ПЕРЕД тем, как браться за такую задачу."),
            i18n.text("skill_briefing_body").format(name=project.name),
        ),
        encoding="utf-8",
    )

    d = skills_dir / "how-to-search"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        _skill(
            "how-to-search",
            i18n._("Как искать по проекту: когда graph_search, когда rlm_query, когда file_info/component_info. Используй, когда нужно что-то найти или понять в кодовой базе."),
            i18n.text("skill_search_body").format(name=project.name),
        ),
        encoding="utf-8",
    )

    _refresh_marketplace()
    log.info("Плагин перегенерирован: %s", plugin_dir)
    return str(plugin_dir)


def remove_project_artifacts(project: Project) -> None:
    """Снести файлы проекта, лежащие вне его каталога: сгенерированный плагин и
    mcp-конфиг чата. Без этого удалённый проект остаётся в marketplace.json и
    его плагин можно поставить в Claude Code уже после удаления."""
    import shutil

    s = get_settings()
    shutil.rmtree(s.data_path / "plugins" / plugin_slug(project), ignore_errors=True)
    try:
        (s.data_path / "mcp" / f"{project.id}.json").unlink(missing_ok=True)
    except OSError:
        pass
    try:
        _refresh_marketplace()
    except OSError:
        pass


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
                "owner": {"name": i18n._("Проекты ИИ")},
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


# описания MCP-инструментов проекта (для UI; сам сервер — app/mcp/server.py)
MCP_TOOLS_INFO = [
    {"name": "project_overview", "description": "Обзор проекта: описание, стек, компоненты, статистика карты знаний"},
    {"name": "graph_search", "description": "Полнотекстовый поиск по карте знаний (файлы, сущности, компоненты, документы, задачи)"},
    {"name": "graph_cypher", "description": "Read-only Cypher-запрос к графу Neo4j"},
    {"name": "list_files", "description": "Реестр файлов проекта с ролями из ИИ-анализа"},
    {"name": "list_documents", "description": "Материалы: транскрипты созвонов, ТЗ, документы"},
    {"name": "read_document", "description": "Чтение текста материала (транскрипта/документа)"},
    {"name": "component_info", "description": "Детали компонента/сервиса: за что отвечает, ключевые файлы с ролями"},
    {"name": "file_info", "description": "Досье файла: роль, сущности, связи, задачи и работы по нему"},
    {"name": "list_decisions", "description": "Соглашения проекта: актуальные решения и смены подходов"},
    {"name": "record_decision", "description": "Зафиксировать решение/смену подхода (обновляет совпадающую тему)"},
    {"name": "git_import", "description": "Импорт истории git (вложенные репо) в канбан выполненными работами"},
    {"name": "rlm_query", "description": "Рекурсивный анализ кодовой базы (RLM): под-агенты читают файлы и возвращают ответ"},
    {"name": "task_list", "description": "Канбан-доска задач проекта"},
    {"name": "task_get", "description": "Задача целиком: досье разбора, файлы, история работ"},
    {"name": "task_create", "description": "Создать задачу в канбане (enrich=true — сразу на RLM-разбор)"},
    {"name": "task_update", "description": "Улучшить/уточнить задачу (название, описание, план)"},
    {"name": "task_move", "description": "Переместить задачу между колонками"},
    {"name": "task_done", "description": "Пометить выполненной с отчётом → суб-агент обновит карту знаний"},
    {"name": "task_enrich", "description": "RLM-проработка: короткая задача → досье (где смотреть, нюансы, как проверить)"},
    {"name": "log_work", "description": "Зафиксировать сделанную работу → суб-агент обновит карту знаний"},
    {"name": "request_reindex", "description": "Запустить обновление индекса (update/reverify)"},
]


def _read_skill_meta(skill_dir: Path) -> dict | None:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return None
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return None
    meta = {"name": skill_dir.name, "description": ""}
    if text.startswith("---"):
        for line in text[3:].split("---", 1)[0].splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip() in ("name", "description"):
                    meta[k.strip()] = v.strip()
    return meta


def plugin_install_info(project: Project) -> dict:
    s = get_settings()
    slug = plugin_slug(project)
    plugin_dir = s.data_path / "plugins" / slug
    marketplace_dir = s.data_path / "plugins"
    skills = []
    skills_dir = plugin_dir / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            meta = _read_skill_meta(child)
            if meta:
                skills.append(meta)
    return {
        "slug": slug,
        "path": str(plugin_dir),
        "exists": plugin_dir.is_dir(),
        "marketplace_path": str(marketplace_dir),
        "install_commands": [
            f"claude plugin marketplace add {marketplace_dir}",
            f"claude plugin install {slug}@projectai",
        ],
        "local_settings_path": str(local_settings_path(project)),
        "local_settings": local_settings_snippet(project),
        "installed_locally": _has_local_install(project),
        "skills": skills,
        "mcp_tools": [{**t, "description": i18n._(t["description"])} for t in MCP_TOOLS_INFO],
    }


# --- установка «только в этот проект» ---------------------------------------
#
# `claude plugin install` пишет в ~/.claude/settings.json, то есть плагин
# становится виден во всех сессиях Claude Code на машине. Те же два ключа
# понимает и `<проект>/.claude/settings.local.json`, а настройки разных уровней
# складываются — поэтому плагин можно включить ровно там, где он нужен.
# Файл именно `.local`, а не общий: в нём абсолютный путь к каталогу плагинов
# конкретной машины, коммитить такое в репозиторий нельзя.


def local_settings_path(project: Project) -> Path:
    return Path(project.root_path) / ".claude" / "settings.local.json"


def local_settings_snippet(project: Project) -> dict:
    marketplace_dir = get_settings().data_path / "plugins"
    return {
        "extraKnownMarketplaces": {
            "projectai": {"source": {"source": "directory", "path": str(marketplace_dir)}}
        },
        "enabledPlugins": {f"{plugin_slug(project)}@projectai": True},
    }


def _has_local_install(project: Project) -> bool:
    path = local_settings_path(project)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool((data.get("enabledPlugins") or {}).get(f"{plugin_slug(project)}@projectai"))


def install_locally(project: Project) -> dict:
    """Включить плагин в `<проект>/.claude/settings.local.json`.

    Чужие ключи в файле не трогаем — только доливаем свои: там могут лежать
    разрешения и хуки, настроенные пользователем.
    """
    path = local_settings_path(project)
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(i18n._("{path} — не читается как JSON: {error}").format(path=path, error=e))
        if not isinstance(data, dict):
            raise ValueError(i18n._("{path} — ожидался объект JSON").format(path=path))

    snippet = local_settings_snippet(project)
    markets = dict(data.get("extraKnownMarketplaces") or {})
    markets.update(snippet["extraKnownMarketplaces"])
    data["extraKnownMarketplaces"] = markets
    enabled = dict(data.get("enabledPlugins") or {})
    enabled.update(snippet["enabledPlugins"])
    data["enabledPlugins"] = enabled

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "plugin": f"{plugin_slug(project)}@projectai"}


def uninstall_locally(project: Project) -> dict:
    """Убрать плагин из настроек проекта, не трогая остальные ключи."""
    path = local_settings_path(project)
    if not path.is_file():
        return {"path": str(path), "removed": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(i18n._("{path} — не читается как JSON: {error}").format(path=path, error=e))

    key = f"{plugin_slug(project)}@projectai"
    removed = bool((data.get("enabledPlugins") or {}).pop(key, None))
    if not data.get("enabledPlugins"):
        data.pop("enabledPlugins", None)
    # маркетплейс общий для всех проектов — убираем, только если больше некого включать
    if not data.get("enabledPlugins"):
        (data.get("extraKnownMarketplaces") or {}).pop("projectai", None)
        if not data.get("extraKnownMarketplaces"):
            data.pop("extraKnownMarketplaces", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "removed": removed}
