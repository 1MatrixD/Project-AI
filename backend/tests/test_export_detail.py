"""Экспорт карты знаний в markdown и деталка задачи (файлы + worklog)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest_asyncio

from .conftest import latest_job, wait_job


@pytest_asyncio.fixture
async def project(user_client: httpx.AsyncClient, sample_project_dir: Path) -> dict:
    r = await user_client.post(
        "/api/projects", json={"name": "Экспорт-проект", "root_path": str(sample_project_dir)}
    )
    project = r.json()
    job = await latest_job(user_client, project["id"], "index")
    await wait_job(user_client, project["id"], job["id"])
    return project


async def test_export_markdown(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    await user_client.post(
        f"/api/projects/{pid}/decisions",
        json={"topic": "Экспорт-тема", "text": "Решение для проверки экспорта."},
    )
    await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Задача в экспорте", "plan": ["шаг раз", "шаг два"]},
    )

    r = await user_client.get(f"/api/projects/{pid}/export/markdown")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers.get("content-disposition", "")
    md = r.text
    assert md.startswith("# Карта знаний: Экспорт-проект")
    # обзор из синтеза, файлы с ролями, соглашения и задачи попали в дамп
    assert "Тестовый проект для проверки пайплайна." in md
    assert "`main.py`" in md
    assert "Экспорт-тема" in md
    assert "- [ ] Задача в экспорте" in md and "план 0/2" in md


async def test_task_detail_files_and_worklog(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    pid = project["id"]
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Деталка"})
    task_id = r.json()["id"]

    # пустая деталка: без файлов и истории
    r = await user_client.get(f"/api/projects/{pid}/tasks/{task_id}/detail")
    assert r.status_code == 200
    d = r.json()
    assert d["task"]["id"] == task_id
    assert d["files"] == []
    assert d["worklog"] == []

    # выполнение с файлами → связи AFFECTS в графе + запись worklog
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/{task_id}/done",
        json={"report": "Сделано в main.py", "files": ["main.py"]},
    )
    assert r.status_code == 200

    r = await user_client.get(f"/api/projects/{pid}/tasks/{task_id}/detail")
    d = r.json()
    paths = [f["path"] for f in d["files"]]
    assert "main.py" in paths
    assert len(d["worklog"]) == 1
    assert "Сделано в main.py" in d["worklog"][0]["description"]
    assert d["worklog"][0]["files"] == ["main.py"]
