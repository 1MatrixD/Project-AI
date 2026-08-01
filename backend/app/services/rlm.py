from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from ..config import get_settings
from ..db import get_sessionmaker
from ..models import Project, ProjectFile
from . import claude_cli, graphdb, roots

log = logging.getLogger("projectai.rlm")

#: Колбэк прогресса: (доля выполненного пайплайна 0..1, что происходит сейчас).
#: Нужен вызывающим, которые показывают ход работы пользователю (проработка задач).
StageCb = Callable[[float, str], Awaitable[None]]

"""Recursive Language Models (MIT, Zhang et al.) в применении к проекту.

Идея RLM: корневая модель НЕ загружает весь контекст (кодовую базу, транскрипты,
документы) в своё окно — контекст лежит «в среде», а модель работает с ним
программно: смотрит выжимки, грепает, выбирает фрагменты и рекурсивно вызывает
саб-модели над этими фрагментами, после чего синтезирует ответ.

Здесь:
- средой выступает каталог проекта + граф знаний Neo4j;
- корневой вызов получает карту знаний (дёшево) и решает, какие файлы важны;
- под-вызовы (sub_query) читают ТОЛЬКО назначенные им файлы и возвращают краткие ответы;
- корень синтезирует финальный ответ из под-ответов, не читая файлы сам.

Тот же механизм доступен чат-ассистенту как MCP-инструмент rlm_query.
"""

# git-история — для распознавания эволюции подходов («объявлено, но не используется»)
GIT_TOOLS = ["Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)", "Bash(git diff:*)"]

SUB_SYSTEM = (
    "You are a focused code analyst. Answer the question using ONLY the assigned files "
    "(Read tool; git log/blame/show allowed for history). Be concise and concrete, "
    "answer in Russian."
)

SUB_PROMPT = """Вопрос: {question}

Назначенные тебе файлы (читай инструментом Read, другие файлы не трогай):
{files}

Дай сжатый ответ по этим файлам: только факты, относящиеся к вопросу, со ссылками на файлы.
Если в этих файлах ответа нет — так и скажи одной строкой."""

ROOT_PLAN_SYSTEM = (
    "You are a research planner over a codebase knowledge map. Answer ONLY with valid JSON."
)

ROOT_PLAN_PROMPT = """Вопрос пользователя по проекту «{project_name}»: {question}

Карта знаний проекта (выжимка):
{graph_context}

Результаты поиска по карте знаний:
{search_results}

Список файлов проекта (путь: роль):
{file_index}

Выбери до {max_groups} групп файлов для рекурсивного анализа под-агентами (паттерн RLM).
Верни СТРОГО JSON:
{{"groups": [{{"focus": "что выяснить у этой группы (по-русски)", "paths": ["файлы"]}}]}}
В каждой группе до {max_files} файлов. Бери только файлы, реально нужные для ответа.
НИКАКОГО текста вне JSON."""

ROOT_SYNTH_SYSTEM = "You synthesize sub-agent findings into one answer. Answer in Russian."

ROOT_SYNTH_PROMPT = """Вопрос пользователя по проекту «{project_name}»: {question}

Карта знаний (выжимка):
{graph_context}

Ответы под-агентов, каждый изучал свою группу файлов:
{sub_answers}

Синтезируй один цельный, конкретный ответ на вопрос (по-русски, со ссылками на файлы).
Если данных не хватает — скажи, чего именно."""


async def sub_query(project: Project, question: str, paths: list[str], model: str | None = None) -> str:
    """Под-вызов RLM: изолированный агент читает только назначенные файлы.

    cwd — основной каталог; файлы дополнительных корней мультирепо
    подставляются абсолютными путями, иначе Read их не найдёт."""
    s = get_settings()
    files = "\n".join(f"- {roots.fs_path_for_prompt(project, p)}" for p in paths[:30])
    prompt = SUB_PROMPT.format(question=question, files=files)
    data = await claude_cli.run_prompt(
        prompt,
        cwd=project.root_path,
        system=SUB_SYSTEM,
        tools=["Read", "Grep", *GIT_TOOLS],
        model=model or s.ai_model,
        reasoning="low",
        timeout=s.claude_timeout_sec,
    )
    return str(data.get("result", ""))


async def _file_index(project_id: uuid.UUID, max_lines: int = 400) -> str:
    async with get_sessionmaker()() as session:
        res = await session.execute(
            select(ProjectFile.rel_path, ProjectFile.kind, ProjectFile.summary)
            .where(ProjectFile.project_id == project_id, ProjectFile.kind.in_(["code", "config", "test", "doc"]))
            .limit(max_lines)
        )
        rows = res.all()
    return "\n".join(f"- {r.rel_path}: {(r.summary or r.kind)[:120]}" for r in rows)[:20000]


async def answer(
    project: Project,
    question: str,
    paths: list[str] | None = None,
    on_stage: StageCb | None = None,
) -> dict:
    """Полный RLM-пайплайн: план → параллельные под-вызовы → синтез.

    `on_stage` вызывается на границах фаз. Пайплайн работает минутами, и без
    таких отметок вызывающий не может показать, что происходит.
    """
    s = get_settings()
    pid = str(project.id)

    async def stage(value: float, detail: str) -> None:
        if on_stage is not None:
            await on_stage(value, detail)

    if paths:
        # пользователь сам ограничил область — один под-вызов
        await stage(0.2, f"читаю файлы: {len(paths)}")
        result = await sub_query(project, question, paths)
        return {"answer": result, "sub_queries": [{"focus": question, "paths": paths}]}

    graph_context = await graphdb.get_project_summary_context(pid, 4000)
    try:
        found = await graphdb.fulltext_search(pid, question, limit=15)
    except Exception:
        found = []
    search_text = "\n".join(
        f"- [{'/'.join(f.get('labels', []))}] {f.get('name') or f.get('path') or f.get('title')}: {(f.get('summary') or '')[:120]}"
        for f in found
    ) or "(ничего не найдено)"

    plan_prompt = ROOT_PLAN_PROMPT.format(
        project_name=project.name,
        question=question,
        graph_context=graph_context,
        search_results=search_text,
        file_index=await _file_index(project.id),
        max_groups=4,
        max_files=12,
    )
    try:
        plan, _ = await claude_cli.run_json_prompt(
            plan_prompt,
            cwd=project.root_path,
            system=ROOT_PLAN_SYSTEM,
            tools=[],
            model=s.ai_model,
            reasoning="medium",
            max_turns=s.claude_max_turns,
            timeout=s.claude_timeout_sec,
        )
    except claude_cli.ClaudeError as e:
        log.warning("RLM-план упал, отвечаем одним агентом: %s", e)
        plan = {"groups": []}

    groups = [
        g for g in (plan.get("groups") or []) if isinstance(g, dict) and g.get("paths")
    ][:4] if isinstance(plan, dict) else []

    if not groups:
        # запасной путь: один агент с обычными инструментами
        await stage(0.25, "план не построен — отвечает один агент")
        data = await claude_cli.run_prompt(
            f"Вопрос по проекту: {question}\nОтветь конкретно, по-русски, со ссылками на файлы.",
            cwd=project.root_path,
            system=f"Контекст проекта:\n{graph_context}",
            tools=["Read", "Grep", "Glob", *GIT_TOOLS],
            model=s.ai_model,
            reasoning="medium",
            timeout=s.claude_timeout_sec,
        )
        return {"answer": str(data.get("result", "")), "sub_queries": []}

    await stage(0.15, f"план готов, групп файлов: {len(groups)}")

    sem = asyncio.Semaphore(s.ai_concurrency)
    finished = 0
    counter_lock = asyncio.Lock()

    async def run_group(g: dict) -> dict:
        nonlocal finished
        focus = str(g.get("focus", question))
        paths_g = [str(p) for p in g["paths"][:12]]
        async with sem:
            try:
                ans = await sub_query(project, f"{question}\nФокус: {focus}", paths_g)
            except claude_cli.ClaudeError as e:
                ans = f"(под-агент упал: {e})"
        async with counter_lock:
            finished += 1
            value = 0.15 + 0.70 * finished / len(groups)
            seen = finished
        await stage(value, f"под-агенты: {seen}/{len(groups)} — {focus[:60]}")
        return {"focus": focus, "paths": paths_g, "answer": ans}

    subs = await asyncio.gather(*(run_group(g) for g in groups))

    await stage(0.9, "свожу ответы под-агентов")

    sub_answers = "\n\n".join(
        f"### Группа: {s_['focus']}\nФайлы: {', '.join(s_['paths'])}\n{s_['answer']}" for s_ in subs
    )
    try:
        synth = await claude_cli.run_prompt(
            ROOT_SYNTH_PROMPT.format(
                project_name=project.name,
                question=question,
                graph_context=graph_context,
                sub_answers=sub_answers[:60000],
            ),
            system=ROOT_SYNTH_SYSTEM,
            tools=[],
            model=s.ai_model,
            reasoning="medium",
            max_turns=s.claude_max_turns,
            timeout=s.claude_timeout_sec,
        )
        final_answer = str(synth.get("result", ""))
    except claude_cli.ClaudeError as e:
        # Под-агенты уже прочитали файлы — это самая дорогая часть работы.
        # Терять её из-за упавшего синтеза нельзя, отдаём их выводы как есть.
        log.warning("RLM-синтез упал (%s), отдаём ответы под-агентов", e)
        final_answer = sub_answers

    return {
        "answer": final_answer,
        "sub_queries": [{"focus": s_["focus"], "paths": s_["paths"]} for s_ in subs],
    }
