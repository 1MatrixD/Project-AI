from __future__ import annotations

import os
import re
from pathlib import Path

from ..models import Project

"""Мультирепо-проекты: несколько каталогов с кодом на один проект.

Основной каталог — project.root_path, его файлы живут без префикса (обратная
совместимость со старыми проектами). Дополнительные каталоги —
project.meta["extra_roots"]: [{"alias", "path"}]; их файлы везде (реестр,
граф, вектора, канбан) ходят с префиксом "alias/". Алиас при добавлении
выбирается так, чтобы не совпадать ни с другими алиасами, ни с записями
верхнего уровня основного каталога — разрешение пути однозначно.
"""


def extra_roots(project_or_meta: Project | dict) -> list[dict]:
    meta = (
        project_or_meta
        if isinstance(project_or_meta, dict)
        else (project_or_meta.meta or {})
    )
    out: list[dict] = []
    for r in meta.get("extra_roots") or []:
        if isinstance(r, dict) and r.get("alias") and r.get("path"):
            out.append({"alias": str(r["alias"]), "path": str(r["path"])})
    return out


def get_roots(project: Project) -> list[tuple[str, str]]:
    """[(alias, abs_path)]; первый — основной каталог с пустым алиасом."""
    return [("", project.root_path)] + [
        (r["alias"], r["path"]) for r in extra_roots(project)
    ]


def split_rel(project: Project, rel_path: str) -> tuple[str, str, str]:
    """Путь из реестра → (alias, локальный путь внутри корня, abs корня)."""
    rel_path = rel_path.replace("\\", "/")
    for r in extra_roots(project):
        prefix = r["alias"] + "/"
        if rel_path.startswith(prefix):
            return r["alias"], rel_path[len(prefix):], r["path"]
    return "", rel_path, project.root_path


def resolve_abs(project: Project, rel_path: str) -> Path:
    _alias, local, root = split_rel(project, rel_path)
    return Path(root) / local


def fs_path_for_prompt(project: Project, rel_path: str) -> str:
    """Путь для промпта агента с cwd=основной каталог: файлы основного корня —
    относительные, файлы других корней — абсолютные (иначе Read их не найдёт)."""
    alias, local, root = split_rel(project, rel_path)
    if not alias:
        return rel_path
    return str(Path(root) / local)


def roots_note(project: Project) -> str:
    """Строка про каталоги проекта для промптов (пустая для однокорневых)."""
    extras = extra_roots(project)
    if not extras:
        return ""
    lines = [f"Проект состоит из нескольких каталогов. Основной: {project.root_path}"]
    for r in extras:
        lines.append(
            f"- пути с префиксом «{r['alias']}/» лежат в каталоге {r['path']}"
            " (обращайся по абсолютному пути)"
        )
    return "\n".join(lines)


def make_alias(path: str, project: Project) -> str:
    """Алиас нового каталога: имя папки без конфликтов с другими алиасами
    и верхним уровнем основного каталога."""
    base = os.path.basename(os.path.normpath(path)) or "repo"
    base = re.sub(r"[^\w.\-]+", "-", base, flags=re.UNICODE).strip("-.") or "repo"
    taken = {r["alias"] for r in extra_roots(project)}
    try:
        taken |= set(os.listdir(project.root_path))
    except OSError:
        pass
    alias, n = base, 2
    while alias in taken:
        alias = f"{base}-{n}"
        n += 1
    return alias
