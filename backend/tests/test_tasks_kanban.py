from __future__ import annotations

from pathlib import Path

import httpx
import pytest_asyncio

from .conftest import latest_job, wait_job


@pytest_asyncio.fixture
async def project(user_client: httpx.AsyncClient, sample_project_dir: Path) -> dict:
    r = await user_client.post(
        "/api/projects", json={"name": "Канбан-проект", "root_path": str(sample_project_dir)}
    )
    assert r.status_code == 201
    project = r.json()
    job = await latest_job(user_client, project["id"], "index")
    await wait_job(user_client, project["id"], job["id"])
    return project


async def test_kanban_flow(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]

    r = await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Первая задача", "description": "описание", "plan": ["шаг"]},
    )
    assert r.status_code == 201
    t1 = r.json()
    assert t1["status"] == "planned" and t1["source"] == "manual"

    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Вторая задача"})
    t2 = r.json()

    # улучшение описания (как это делает ИИ через MCP)
    r = await user_client.patch(
        f"/api/projects/{pid}/tasks/{t1['id']}",
        json={"description": "уточнённое описание", "plan": ["шаг 1", "шаг 2"]},
    )
    assert r.json()["description"] == "уточнённое описание"

    # перенос колонки
    r = await user_client.patch(f"/api/projects/{pid}/tasks/{t1['id']}", json={"status": "in_progress"})
    assert r.json()["status"] == "in_progress"

    r = await user_client.patch(f"/api/projects/{pid}/tasks/{t1['id']}", json={"status": "bogus"})
    assert r.status_code == 400

    # reorder
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/reorder",
        json={"status": "planned", "ordered_ids": [t2["id"]]},
    )
    assert r.status_code == 200

    # done с отчётом → worklog → knowledge_update
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/{t1['id']}/done",
        json={"report": "Сделано в тесте", "files": ["main.py"]},
    )
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "done" and done["done_at"]
    assert "Сделано в тесте" in done["report"]

    r = await user_client.get(f"/api/projects/{pid}/worklog")
    entries = r.json()
    assert entries and "Первая задача" in entries[0]["description"]

    job = await latest_job(user_client, pid, "knowledge_update")
    assert job is not None
    job = await wait_job(user_client, pid, job["id"])
    assert job["status"] == "done"
    assert job["stats"]["worklog_synced"] >= 1

    # задача есть в графе
    r = await user_client.post(
        f"/api/projects/{pid}/graph/cypher",
        json={"query": "MATCH (t:Task {project_id: $pid}) RETURN t.title AS title, t.status AS status"},
    )
    rows = r.json()
    assert any(row["title"] == "Первая задача" and row["status"] == "done" for row in rows)


async def test_rlm_survives_failed_synthesis(project: dict, monkeypatch) -> None:
    """Упавшая финальная сводка не должна съедать работу под-агентов.

    Под-агенты уже прочитали файлы — это самая дорогая часть RLM. Раньше любая
    ошибка синтеза (например, упёршийся в потолок ходов вызов) роняла весь
    пайплайн и исследование терялось целиком.
    """
    import uuid as _uuid

    from app.db import get_sessionmaker
    from app.models import Project as ProjectModel
    from app.services import rlm

    monkeypatch.setenv("FAKE_CLAUDE_FAIL_SYNTH", "1")
    async with get_sessionmaker()() as session:
        proj = await session.get(ProjectModel, _uuid.UUID(project["id"]))

    res = await rlm.answer(proj, "как устроен main.py?")

    assert res["sub_queries"], res
    # вместо исключения вернулись выводы под-агентов, а не пустота
    assert "Группа:" in res["answer"], res["answer"][:300]


async def test_enrich_task_rlm(
    user_client: httpx.AsyncClient, project: dict, monkeypatch
) -> None:
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Починить кнопку", "description": "коротко с созвона"},
    )
    task = r.json()
    assert task["extra"] == {}

    # проработка идёт минутами, поэтому следим, что прогресс сообщается по ходу дела,
    # а не единственным разом в самом конце
    from app.jobs_runner import runner

    seen: list[tuple[float, str]] = []
    original_report = runner.report

    async def spy_report(job_id, progress, detail="", stats=None):
        seen.append((progress, detail))
        await original_report(job_id, progress, detail, stats)

    monkeypatch.setattr(runner, "report", spy_report)

    r = await user_client.post(f"/api/projects/{pid}/tasks/{task['id']}/enrich")
    assert r.status_code == 200
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["enriched"] == 1

    values = [p for p, _ in seen]
    assert len(values) >= 3, seen
    assert values == sorted(values), seen
    # есть промежуточные отметки, а не только «начали» и «всё»
    assert any(0.01 < p < 0.9 for p in values), seen
    assert any("исследование" in d for _, d in seen), seen

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    enriched = next(t for t in r.json() if t["id"] == task["id"])
    assert "Детальная проработка" in enriched["description"]
    assert enriched["extra"]["enriched"] is True
    assert enriched["extra"]["original_description"] == "коротко с созвона"
    assert "main.py" in enriched["extra"]["files"]
    assert enriched["extra"]["related"][0]["relation"] == "overlaps"
    # план — чекбокс-шаги
    assert enriched["plan"][0] == {"text": "Посмотреть обработчик в main.py", "done": False}

    # тоггл чекбокса
    plan = enriched["plan"]
    plan[0]["done"] = True
    r = await user_client.patch(
        f"/api/projects/{pid}/tasks/{task['id']}", json={"plan": plan}
    )
    assert r.json()["plan"][0]["done"] is True


async def test_verify_tasks(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    # фейковый claude отвечает yes только для "Сделать фичу А"
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Сделать фичу А"})
    ta = r.json()
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Нереализованная фича"})
    tb = r.json()

    r = await user_client.post(f"/api/projects/{pid}/tasks/verify")
    assert r.status_code == 200
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["stats"]["done"] >= 1

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    by_id = {t["id"]: t for t in r.json()}
    assert by_id[ta["id"]]["status"] == "done"
    assert "[ИИ-проверка]" in by_id[ta["id"]]["report"]
    assert by_id[tb["id"]]["status"] == "planned"
