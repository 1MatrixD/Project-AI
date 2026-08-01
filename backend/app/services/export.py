"""Экспорт карты знаний проекта в человекочитаемый markdown."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..db import get_sessionmaker
from ..models import Decision, Material, Project, ProjectFile, TaskItem

STATUS_LABELS = {
    "planned": "Запланировано",
    "in_progress": "В работе",
    "review": "Ревью",
    "done": "Готово",
    "cancelled": "Отменено",
}


def _md_escape(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ").strip()


async def export_markdown(project: Project) -> str:
    """Дамп карты знаний: обзор, компоненты, соглашения, задачи, файлы."""
    meta = project.meta or {}
    overview = meta.get("overview") or {}
    detect = meta.get("detect") or {}
    stats = meta.get("stats") or {}

    async with get_sessionmaker()() as session:
        files = list(
            (
                await session.execute(
                    select(ProjectFile)
                    .where(ProjectFile.project_id == project.id)
                    .order_by(ProjectFile.rel_path)
                )
            ).scalars()
        )
        decisions = list(
            (
                await session.execute(
                    select(Decision)
                    .where(Decision.project_id == project.id)
                    .order_by(Decision.updated_at.desc())
                )
            ).scalars()
        )
        tasks = list(
            (
                await session.execute(
                    select(TaskItem)
                    .where(TaskItem.project_id == project.id)
                    .order_by(TaskItem.status, TaskItem.order)
                )
            ).scalars()
        )
        materials = list(
            (
                await session.execute(
                    select(Material)
                    .where(Material.project_id == project.id)
                    .order_by(Material.created_at)
                )
            ).scalars()
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    analyzed = sum(1 for f in files if f.analysis_status == "analyzed")
    out: list[str] = []
    out.append(f"# Карта знаний: {project.name}")
    out.append("")
    out.append(f"> Экспортировано {now} · файлов: {len(files)}, проанализировано ИИ: {analyzed}")
    out.append(f"> Каталог: `{project.root_path}`")
    out.append("")

    # --- обзор ---
    if overview.get("summary"):
        out.append("## Обзор")
        out.append("")
        out.append(str(overview["summary"]).strip())
        out.append("")
    badges = []
    if detect.get("project_kinds"):
        badges.append("**Тип:** " + ", ".join(map(str, detect["project_kinds"])))
    if detect.get("stack"):
        badges.append("**Стек:** " + ", ".join(map(str, detect["stack"])))
    if badges:
        out.extend(badges)
        out.append("")

    # --- компоненты ---
    comps = overview.get("components") or []
    if comps:
        out.append("## Компоненты")
        out.append("")
        for c in comps:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            out.append(f"### {c['name']} ({c.get('kind', 'module')})")
            out.append("")
            if c.get("summary"):
                out.append(str(c["summary"]).strip())
            paths = c.get("paths") or []
            if paths:
                out.append("")
                out.append("Ключевые файлы: " + ", ".join(f"`{p}`" for p in paths[:15]))
            out.append("")

    features = overview.get("business_logic") or []
    if features:
        out.append("## Бизнес-логика")
        out.append("")
        for f in features:
            if isinstance(f, dict) and f.get("name"):
                out.append(f"- **{f['name']}** — {_md_escape(str(f.get('summary', '')))}")
        out.append("")

    if overview.get("conventions"):
        out.append("## Конвенции кода")
        out.append("")
        out.append(str(overview["conventions"]).strip())
        out.append("")

    how_to = overview.get("how_to") or {}
    if isinstance(how_to, dict) and how_to:
        out.append("## Как запускать")
        out.append("")
        for k, v in how_to.items():
            out.append(f"- **{k}**: `{_md_escape(str(v))}`")
        out.append("")

    # --- соглашения ---
    if decisions:
        out.append("## Соглашения проекта")
        out.append("")
        out.append("Актуальные решения — «как принято сейчас» (не баги, а осознанный выбор):")
        out.append("")
        for d in decisions:
            out.append(f"- **{_md_escape(d.topic)}** — {_md_escape(d.text)}")
        out.append("")

    # --- задачи ---
    if tasks:
        out.append("## Задачи")
        out.append("")
        by_status: dict[str, list[TaskItem]] = {}
        for t in tasks:
            by_status.setdefault(t.status, []).append(t)
        for status in ("planned", "in_progress", "review", "done"):
            items = by_status.get(status) or []
            if not items:
                continue
            out.append(f"### {STATUS_LABELS.get(status, status)} ({len(items)})")
            out.append("")
            for t in items:
                mark = "x" if status == "done" else " "
                line = f"- [{mark}] {_md_escape(t.title)}"
                plan = t.plan or []
                if plan:
                    done_steps = sum(1 for p in plan if isinstance(p, dict) and p.get("done"))
                    line += f" _(план {done_steps}/{len(plan)})_"
                out.append(line)
            out.append("")

    # --- материалы ---
    if materials:
        out.append("## Материалы")
        out.append("")
        for m in materials:
            line = f"- **{_md_escape(m.filename)}** ({m.status})"
            if m.summary:
                line += f" — {_md_escape(m.summary)[:200]}"
            out.append(line)
        out.append("")

    # --- файлы по каталогам ---
    analyzed_files = [f for f in files if f.summary]
    if analyzed_files:
        out.append("## Файлы")
        out.append("")
        by_dir: dict[str, list[ProjectFile]] = {}
        for f in analyzed_files:
            d = f.rel_path.rsplit("/", 1)[0] if "/" in f.rel_path else "."
            by_dir.setdefault(d, []).append(f)
        for d in sorted(by_dir):
            out.append(f"### `{d}/`" if d != "." else "### корень")
            out.append("")
            for f in by_dir[d]:
                out.append(f"- `{f.rel_path}` — {_md_escape(f.summary or '')[:220]}")
            out.append("")

    return "\n".join(out).strip() + "\n"
