from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest_asyncio

from .conftest import latest_job, wait_job


@pytest_asyncio.fixture
async def project(user_client: httpx.AsyncClient, sample_project_dir: Path) -> dict:
    r = await user_client.post(
        "/api/projects", json={"name": "Проект соглашений", "root_path": str(sample_project_dir)}
    )
    project = r.json()
    job = await latest_job(user_client, project["id"], "index")
    await wait_job(user_client, project["id"], job["id"])
    return project


async def test_decisions_crud(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/decisions",
        json={"topic": "Роли в админке", "text": "Роль ORGANIZER упразднена, MANAGER + пермишены."},
    )
    assert r.status_code == 201
    d = r.json()
    assert d["source"] == "manual"

    # совпадающая тема обновляет, а не дублирует
    r = await user_client.post(
        f"/api/projects/{pid}/decisions",
        json={"topic": "Роли в админке", "text": "Уточнение: пермишены задаются в permissions.py."},
    )
    assert r.status_code == 201
    r = await user_client.get(f"/api/projects/{pid}/decisions")
    items = r.json()
    assert len(items) == 1
    assert "permissions.py" in items[0]["text"]

    r = await user_client.patch(
        f"/api/projects/{pid}/decisions/{d['id']}", json={"text": "Финальная версия."}
    )
    assert r.json()["text"] == "Финальная версия."

    r = await user_client.delete(f"/api/projects/{pid}/decisions/{d['id']}")
    assert r.status_code == 204
    r = await user_client.get(f"/api/projects/{pid}/decisions")
    assert r.json() == []


async def test_material_creates_decisions(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/materials",
        files={"file": ("call_notes.txt", "Созвон: решили сменить подход.".encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201
    job = await latest_job(user_client, pid, "process_material")
    job = await wait_job(user_client, pid, job["id"])
    assert job["status"] == "done"
    assert job["stats"].get("decisions_created") == 1

    r = await user_client.get(f"/api/projects/{pid}/decisions")
    ds = r.json()
    assert any(d["topic"] == "Роли в тесте" and d["source"] == "doc" for d in ds)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


async def test_git_import(user_client: httpx.AsyncClient, sample_project_dir: Path) -> None:
    # git-репо в ПОДПАПКЕ (монорепо-кейс)
    sub = sample_project_dir / "service"
    sub.mkdir()
    (sub / "api.py").write_text("x = 1\n", encoding="utf-8")
    _git(sub, "init", "-q")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-qm", "feat: api endpoint")
    (sub / "api.py").write_text("x = 2\n", encoding="utf-8")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-qm", "fix: api bug")

    r = await user_client.post(
        "/api/projects", json={"name": "Гит-проект", "root_path": str(sample_project_dir)}
    )
    pid = r.json()["id"]
    job = await latest_job(user_client, pid, "index")
    await wait_job(user_client, pid, job["id"])

    # существующая открытая задача, которую коммиты должны закрыть
    await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Сделать фичу А"})

    r = await user_client.post(f"/api/projects/{pid}/git/import")
    assert r.status_code == 200
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["repos"] >= 1
    assert job["stats"]["commits_new"] >= 2
    assert job["stats"]["tasks_created"] >= 1
    assert job["stats"]["tasks_closed"] == 1

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    tasks = r.json()
    git_task = next(t for t in tasks if t["source"] == "git")
    assert git_task["status"] == "done"
    assert "[git-импорт]" in git_task["report"]
    closed = next(t for t in tasks if t["title"] == "Сделать фичу А")
    assert closed["status"] == "done"
    assert "Подтверждено коммитами" in closed["report"]

    # повторный импорт не плодит дубликаты
    r = await user_client.post(f"/api/projects/{pid}/git/import")
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["stats"]["commits_new"] == 0
