from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, update

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import runner
from ..models import Project, TaskItem, utcnow
from . import claude_cli, graphdb
from .decisions import get_decisions_text
from .scanner import IGNORED_DIRS

log = logging.getLogger("projectai.git")

"""Импорт истории git в канбан.

Монорепо: .git может лежать в подпапках — репозитории ищутся рекурсивно.
Коммиты группируются ИИ в единицы работы: совпадающие с существующими задачами
закрывают их (с отчётом и ссылками на коммиты), остальные становятся done-задачами
source=git. Так доска отражает и то, что уже сделано, и то, что ещё нет.
"""

GIT_IMPORT_SYSTEM = (
    "You are a tech lead reconstructing a project work log from git history. "
    "Answer ONLY with valid JSON."
)

GIT_IMPORT_PROMPT = """Проект «{project_name}», репозиторий `{repo}`.

Контекст проекта:
{project_context}

Соглашения проекта:
{decisions}

Существующие задачи канбана (title [статус]):
{existing_tasks}

Коммиты (новые, ещё не импортированные; от новых к старым):
{commits}

Сгруппируй коммиты в единицы выполненной работы. Верни СТРОГО JSON:
{{
  "groups": [
    {{
      "title": "короткое название работы (по-русски)",
      "description": "что сделано, судя по коммитам и файлам (по-русски, конкретно)",
      "commits": ["короткие_хэши"],
      "files": ["до 15 ключевых файлов"],
      "matches_existing_task": "ТОЧНОЕ название существующей задачи из списка или null"
    }}
  ]
}}
Правила:
- Группируй связанные коммиты в одну работу (фича/фикс), не дроби на каждый коммит.
- matches_existing_task заполняй ТОЛЬКО при явном смысловом совпадении с существующей задачей.
- Пропускай шумовые коммиты (bump версий, форматирование, merge) — не создавай из них групп.
- Пути файлов указывай с префиксом `{repo_prefix}` (относительно корня проекта).
- НИКАКОГО текста вне JSON."""


@dataclass
class Commit:
    hash: str
    author: str
    date: str
    subject: str
    body: str
    files: list[str] = field(default_factory=list)


def find_git_repos(root: str, max_depth: int = 3) -> list[str]:
    """Ищет каталоги с .git (включая корень и вложенные — монорепо)."""
    repos: list[str] = []
    root = os.path.abspath(root)
    base_depth = root.count(os.sep)
    for dirpath, dirnames, _ in os.walk(root):
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
            continue
        if ".git" in dirnames or os.path.isdir(os.path.join(dirpath, ".git")):
            repos.append(dirpath)
            dirnames[:] = []  # вложенные репо внутри репо не ищем
            continue
        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_DIRS and d != ".git"]
    return repos


def read_git_log(repo: str, limit: int = 150, since_days: int | None = None) -> list[Commit]:
    """Читает историю коммитов с файлами (без merge-коммитов), опционально за период."""
    fmt = "%x1e%h%x1f%an%x1f%ad%x1f%s%x1f%b%x1f"
    args = [
        "git", "log", f"-n{limit}", "--no-merges", "--date=short",
        f"--pretty=format:{fmt}", "--name-only",
    ]
    if since_days:
        args.insert(2, f"--since={since_days} days ago")
    try:
        proc = subprocess.run(
            args,
            cwd=repo,
            capture_output=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("git log в %s не удался: %s", repo, e)
        return []
    if proc.returncode != 0:
        log.warning("git log в %s: %s", repo, proc.stderr.decode(errors="replace")[:300])
        return []
    out = proc.stdout.decode("utf-8", errors="replace")
    commits: list[Commit] = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f")
        if len(parts) < 6:
            continue
        h, author, date, subject, body, tail = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        files = [f.strip().replace("\\", "/") for f in tail.strip().splitlines() if f.strip()]
        commits.append(
            Commit(
                hash=h.strip(),
                author=author.strip(),
                date=date.strip(),
                subject=subject.strip()[:200],
                body=body.strip()[:400],
                files=files[:30],
            )
        )
    return commits


def _fmt_commits(commits: list[Commit]) -> str:
    lines = []
    for c in commits:
        line = f"- {c.hash} [{c.date}] {c.subject}"
        if c.body:
            line += f" | {c.body[:150]}"
        if c.files:
            line += f" | файлы: {', '.join(c.files[:8])}"
        lines.append(line)
    return "\n".join(lines)


async def git_import(job_id: uuid.UUID, project_id: uuid.UUID, params: dict) -> dict:
    s = get_settings()
    per_repo = max(1, min(1000, int(params.get("per_repo_limit", 150))))
    since_days = params.get("since_days")
    since_days = int(since_days) if since_days else None
    maker = get_sessionmaker()
    async with maker() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Проект не найден")
        imported: set[str] = set(project.meta.get("git_imported", []))

    await runner.report(job_id, 0.05, "Поиск git-репозиториев")
    repos = await asyncio.to_thread(find_git_repos, project.root_path)
    if not repos:
        return {"repos": 0, "commits_new": 0, "tasks_created": 0, "tasks_closed": 0}

    from .task_enrich import list_existing_tasks_text

    context = await graphdb.get_project_summary_context(str(project_id), 3000)
    decisions = await get_decisions_text(project_id)

    stats = {"repos": len(repos), "commits_new": 0, "tasks_created": 0, "tasks_closed": 0, "groups": 0}
    root_abs = os.path.abspath(project.root_path)

    for idx, repo in enumerate(repos):
        rel_repo = os.path.relpath(repo, root_abs).replace("\\", "/")
        repo_prefix = "" if rel_repo == "." else rel_repo + "/"
        await runner.report(
            job_id, 0.1 + 0.8 * idx / len(repos), f"Импорт git: {rel_repo or 'корень'}"
        )
        commits = await asyncio.to_thread(read_git_log, repo, per_repo, since_days)
        fresh = [c for c in commits if c.hash not in imported]
        if not fresh:
            continue
        stats["commits_new"] += len(fresh)

        # порции, чтобы промпт не разрастался
        for chunk_start in range(0, len(fresh), 60):
            chunk = fresh[chunk_start : chunk_start + 60]
            existing = await list_existing_tasks_text(project_id)
            prompt = GIT_IMPORT_PROMPT.format(
                project_name=project.name,
                repo=rel_repo or ".",
                project_context=context,
                decisions=decisions,
                existing_tasks=existing,
                commits=_fmt_commits(chunk),
                repo_prefix=repo_prefix,
            )
            try:
                obj, _ = await claude_cli.run_json_prompt(
                    prompt,
                    system=GIT_IMPORT_SYSTEM,
                    tools=[],
                    model=s.ai_model,
                    reasoning="medium",
                    max_turns=1,
                    timeout=s.claude_timeout_sec,
                )
            except claude_cli.ClaudeError as e:
                log.warning("Импорт git-порции %s упал: %s", rel_repo, e)
                continue
            groups = obj.get("groups") if isinstance(obj, dict) else None
            for g in groups or []:
                if not isinstance(g, dict) or not g.get("title"):
                    continue
                await _apply_group(project, g, rel_repo, stats)
                stats["groups"] += 1
            imported.update(c.hash for c in chunk)

    async with maker() as session:
        db_project = await session.get(Project, project_id)
        meta = dict(db_project.meta)
        meta["git_imported"] = sorted(imported)[-3000:]
        db_project.meta = meta
        await session.commit()
    return stats


async def _apply_group(project: Project, g: dict, repo: str, stats: dict) -> None:
    title = str(g["title"])[:300]
    description = str(g.get("description", ""))[:6000]
    commits = [str(c)[:16] for c in (g.get("commits") or [])[:40]]
    files = [str(f)[:500] for f in (g.get("files") or [])[:20]]
    matches = g.get("matches_existing_task")
    commits_line = ", ".join(commits)
    pid = str(project.id)

    async with get_sessionmaker()() as session:
        if matches:
            res = await session.execute(
                select(TaskItem).where(
                    TaskItem.project_id == project.id,
                    TaskItem.title.ilike(str(matches).strip()),
                    TaskItem.status.in_(["planned", "in_progress", "review"]),
                )
            )
            task = res.scalar_one_or_none()
            if task is not None:
                task.status = "done"
                task.done_at = utcnow()
                task.report = (
                    f"[git-импорт] Подтверждено коммитами ({repo}): {commits_line}.\n{description}"
                )[:8000]
                task.extra = {**(task.extra or {}), "commits": commits, "repo": repo}
                await session.commit()
                await graphdb.upsert_task_node(pid, str(task.id), task.title, "done", files)
                stats["tasks_closed"] += 1
                return
        # дубликаты уже импортированных групп не плодим
        res = await session.execute(
            select(TaskItem).where(
                TaskItem.project_id == project.id, TaskItem.title.ilike(title)
            )
        )
        if res.scalar_one_or_none() is not None:
            return
        task = TaskItem(
            project_id=project.id,
            title=title,
            description=description,
            status="done",
            source="git",
            report=f"[git-импорт] Коммиты ({repo}): {commits_line}"[:8000],
            done_at=utcnow(),
            extra={"commits": commits, "repo": repo, "files": files},
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
    await graphdb.upsert_task_node(pid, str(task.id), title, "done", files)
    stats["tasks_created"] += 1
