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

Существующие задачи канбана (с планами; номера шагов — для пометки выполненного):
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
      "matches_existing_task": "ТОЧНОЕ название существующей задачи из списка или null",
      "coverage": "full|partial",
      "completed_plan_steps": [1, 3]
    }}
  ]
}}
Правила:
- Группируй связанные коммиты в одну работу (фича/фикс), не дроби на каждый коммит.
- matches_existing_task заполняй ТОЛЬКО при явном смысловом совпадении с существующей задачей.
- coverage: "full" — коммиты полностью закрывают задачу; "partial" — сделана только часть.
  При partial перечисли в completed_plan_steps НОМЕРА выполненных шагов плана этой задачи
  (по нумерации из списка выше). Задача при partial НЕ закрывается — только шаги.
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


def _run_git(repo: str, *args: str, timeout: int = 60) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("git %s в %s не удался: %s", args[0] if args else "?", repo, e)
        return None
    if proc.returncode != 0:
        log.warning("git %s в %s: %s", " ".join(args[:2]), repo, proc.stderr.decode(errors="replace")[:200])
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def repo_info(repo: str, root: str) -> dict:
    """Сводка по репозиторию: ветки, текущая ветка, последний коммит."""
    rel = os.path.relpath(repo, os.path.abspath(root)).replace("\\", "/")
    current = (_run_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or "HEAD"
    local = (_run_git(repo, "branch", "--format=%(refname:short)") or "").splitlines()
    remote = (_run_git(repo, "branch", "-r", "--format=%(refname:short)") or "").splitlines()
    branches: list[str] = []
    for b in [*local, *remote]:
        b = b.strip()
        if b and "HEAD" not in b and b not in branches:
            branches.append(b)
    last = (_run_git(repo, "log", "-1", "--date=short", "--pretty=format:%ad %s") or "").strip()
    total = (_run_git(repo, "rev-list", "--count", "HEAD") or "0").strip()
    return {
        "path": "." if rel == "." else rel,
        "current_branch": current,
        "branches": branches[:30],
        "last_commit": last[:200],
        "total_commits": int(total) if total.isdigit() else 0,
    }


def read_git_log(
    repo: str,
    limit: int = 150,
    since_days: int | None = None,
    branch: str | None = None,
) -> list[Commit]:
    """Читает историю коммитов с файлами (без merge-коммитов), опционально за период/ветку."""
    fmt = "%x1e%h%x1f%an%x1f%ad%x1f%s%x1f%b%x1f"
    args = [
        "git", "log", f"-n{limit}", "--no-merges", "--date=short",
        f"--pretty=format:{fmt}", "--name-only",
    ]
    if branch:
        args.insert(2, branch)
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


async def _existing_tasks_with_plans(project_id: uuid.UUID) -> str:
    """Задачи с нумерованными шагами плана — чтобы ИИ мог пометить сделанные шаги."""
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(TaskItem)
            .where(TaskItem.project_id == project_id)
            .order_by(TaskItem.created_at.desc())
            .limit(60)
        )
        rows = list(res.scalars())
    status_ru = {
        "planned": "запланирована",
        "in_progress": "в работе",
        "review": "на ревью",
        "done": "СДЕЛАНА",
        "cancelled": "отменена",
    }
    lines: list[str] = []
    for t in rows:
        lines.append(f"- «{t.title}» [{status_ru.get(t.status, t.status)}]")
        for i, step in enumerate(t.plan or [], start=1):
            if isinstance(step, dict):
                mark = "сделан" if step.get("done") else "не сделан"
                lines.append(f"    {i}) {str(step.get('text', ''))[:150]} [{mark}]")
    return "\n".join(lines) or "(задач ещё нет)"


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
    default_limit = max(1, min(1000, int(params.get("per_repo_limit", 150))))
    default_since = params.get("since_days")
    default_since = int(default_since) if default_since else None
    # per-repo конфиги из модалки: [{path, branch, since_days, limit}]
    repo_configs: dict[str, dict] = {
        str(rc.get("path", "")).replace("\\", "/"): rc
        for rc in (params.get("repos") or [])
        if isinstance(rc, dict) and rc.get("path")
    }
    maker = get_sessionmaker()
    async with maker() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Проект не найден")
        imported: set[str] = set(project.meta.get("git_imported", []))

    await runner.report(job_id, 0.05, "Поиск git-репозиториев")
    from .roots import get_roots

    # все корни мультирепо-проекта; ключ репо: "." | "sub" | "alias" | "alias/sub"
    repo_list: list[tuple[str, str]] = []
    for alias, root in get_roots(project):
        for r in await asyncio.to_thread(find_git_repos, root):
            rel = os.path.relpath(r, os.path.abspath(root)).replace("\\", "/")
            if rel == ".":
                key = alias or "."
            elif alias:
                key = f"{alias}/{rel}"
            else:
                key = rel
            repo_list.append((r, key))
    if repo_configs:
        repo_list = [(r, k) for r, k in repo_list if k in repo_configs]
    if not repo_list:
        return {"repos": 0, "commits_new": 0, "tasks_created": 0, "tasks_closed": 0}

    context = await graphdb.get_project_summary_context(str(project_id), 3000)
    decisions = await get_decisions_text(project_id)

    stats = {"repos": len(repo_list), "commits_new": 0, "tasks_created": 0, "tasks_closed": 0, "groups": 0}

    try:
        await _import_repos(
            job_id, project, repo_list, repo_configs, imported, stats,
            context, decisions, default_limit, default_since,
        )
    finally:
        # хэши обработанных порций сохраняем даже при отмене — иначе
        # повторный импорт надублирует задачи
        async with maker() as session:
            db_project = await session.get(Project, project_id)
            meta = dict(db_project.meta)
            meta["git_imported"] = sorted(imported)[-3000:]
            db_project.meta = meta
            await session.commit()
    return stats


async def _import_repos(
    job_id: uuid.UUID,
    project: Project,
    repos: list[tuple[str, str]],
    repo_configs: dict,
    imported: set[str],
    stats: dict,
    context: str,
    decisions: str,
    default_limit: int,
    default_since: int | None,
) -> None:
    s = get_settings()
    for idx, (repo, rel_repo) in enumerate(repos):
        runner.check_cancelled(job_id)
        repo_prefix = "" if rel_repo == "." else rel_repo + "/"
        await runner.report(
            job_id,
            0.1 + 0.8 * idx / len(repos),
            f"Импорт git: {'корень' if rel_repo == '.' else rel_repo}",
        )
        rc = repo_configs.get(rel_repo, {})
        limit = max(1, min(1000, int(rc.get("limit", default_limit))))
        since = int(rc["since_days"]) if rc.get("since_days") else default_since
        branch = str(rc["branch"])[:100] if rc.get("branch") else None
        commits = await asyncio.to_thread(read_git_log, repo, limit, since, branch)
        fresh = [c for c in commits if c.hash not in imported]
        if not fresh:
            continue
        stats["commits_new"] += len(fresh)

        # порции, чтобы промпт не разрастался
        for chunk_start in range(0, len(fresh), 60):
            runner.check_cancelled(job_id)
            chunk = fresh[chunk_start : chunk_start + 60]
            existing = await _existing_tasks_with_plans(project.id)
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
                    max_turns=s.claude_max_turns,
                    timeout=s.claude_timeout_sec,
                )
            except claude_cli.ClaudeError as e:
                log.warning("Импорт git-порции %s упал: %s", rel_repo, e)
                continue
            groups = obj.get("groups") if isinstance(obj, dict) else None
            commit_dates = {c.hash: c.date for c in chunk}
            for g in groups or []:
                if not isinstance(g, dict) or not g.get("title"):
                    continue
                await _apply_group(project, g, rel_repo, stats, commit_dates)
                stats["groups"] += 1
            imported.update(c.hash for c in chunk)


def _order_from_dates(commits: list[str], commit_dates: dict[str, str]) -> float:
    """Свежая работа — выше в колонке: order = -дни от эпохи новейшего коммита группы."""
    import datetime as dt

    best = 0
    for h in commits:
        d = commit_dates.get(h)
        if not d:
            continue
        try:
            days = (dt.date.fromisoformat(d) - dt.date(1970, 1, 1)).days
            best = max(best, days)
        except ValueError:
            continue
    return -float(best)


async def _apply_group(
    project: Project, g: dict, repo: str, stats: dict, commit_dates: dict[str, str] | None = None
) -> None:
    title = str(g["title"])[:300]
    description = str(g.get("description", ""))[:6000]
    commits = [str(c)[:16] for c in (g.get("commits") or [])[:40]]
    files = [str(f)[:500] for f in (g.get("files") or [])[:20]]
    matches = g.get("matches_existing_task")
    commits_line = ", ".join(commits)
    pid = str(project.id)

    coverage = str(g.get("coverage", "full"))
    steps = [int(x) for x in (g.get("completed_plan_steps") or []) if str(x).isdigit()]

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
                if coverage == "partial":
                    # закрываем только выполненные шаги плана, задача остаётся открытой
                    plan = list(task.plan or [])
                    marked = 0
                    for n in steps:
                        if 1 <= n <= len(plan) and isinstance(plan[n - 1], dict):
                            if not plan[n - 1].get("done"):
                                plan[n - 1] = {**plan[n - 1], "done": True}
                                marked += 1
                    task.plan = plan
                    if task.status == "planned":
                        task.status = "in_progress"
                    note = (
                        f"[git-импорт] Частично выполнено коммитами ({repo}): {commits_line}."
                        f" Шаги плана: {', '.join(map(str, steps)) or '—'}.\n{description}"
                    )
                    task.report = (f"{task.report}\n\n{note}" if task.report else note)[:8000]
                    task.extra = {
                        **(task.extra or {}),
                        "commits": [*(task.extra or {}).get("commits", []), *commits][:80],
                        "repo": repo,
                    }
                    await session.commit()
                    await graphdb.upsert_task_node(pid, str(task.id), task.title, task.status, files)
                    stats["tasks_partial"] = stats.get("tasks_partial", 0) + 1
                    stats["plan_steps_marked"] = stats.get("plan_steps_marked", 0) + marked
                    return
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
            order=_order_from_dates(commits, commit_dates or {}),
            extra={"commits": commits, "repo": repo, "files": files},
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
    await graphdb.upsert_task_node(pid, str(task.id), title, "done", files)
    stats["tasks_created"] += 1
