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


async def test_decision_change_regenerates_plugin(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    """Скиллы плагина включают соглашения, поэтому правка соглашения перегенерирует
    плагин сразу (генерация без ИИ) — кнопка «когда перегенерировать» не нужна."""
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/decisions",
        json={"topic": "Тема для плагина", "text": "Решение, которое обязано попасть в скилл."},
    )
    assert r.status_code == 201
    r = await user_client.get(f"/api/projects/{pid}/plugin")
    skill = Path(r.json()["path"]) / "skills" / "architecture" / "SKILL.md"
    assert "Тема для плагина" in skill.read_text(encoding="utf-8")


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


async def test_tool_access_config(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    r = await user_client.get(f"/api/projects/{pid}/tool-access")
    data = r.json()
    # дефолты: чату можно всё, плагину — всё кроме технических
    assert data["access"]["chat"]["admin"] is True
    assert data["access"]["plugin"]["admin"] is False
    assert data["access"]["plugin"]["tasks"] is True

    r = await user_client.get(f"/api/projects/{pid}/tool-access", params={"surface": "plugin"})
    allowed = r.json()["allowed_tools"]
    assert "task_list" in allowed and "git_import" not in allowed

    # выключаем плагину задачи, включаем технические
    access = data["access"]
    access["plugin"]["tasks"] = False
    access["plugin"]["admin"] = True
    r = await user_client.put(f"/api/projects/{pid}/tool-access", json=access)
    assert r.status_code == 200

    r = await user_client.get(f"/api/projects/{pid}/tool-access", params={"surface": "plugin"})
    allowed = r.json()["allowed_tools"]
    assert "task_list" not in allowed and "git_import" in allowed


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

    # существующая открытая задача, которую коммиты должны закрыть целиком
    await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Сделать фичу А"})
    # и задача, сделанная наполовину: закрыться должен только шаг 1 плана
    r = await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Частичная фича В", "plan": ["сделать бэк", "сделать фронт"]},
    )
    partial_id = r.json()["id"]

    r = await user_client.post(
        f"/api/projects/{pid}/git/import",
        json={"since_days": 3650, "per_repo_limit": 100},
    )
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

    # частично сделанная: шаг 1 отмечен, задача НЕ закрыта, перешла в работу
    partial = next(t for t in tasks if t["id"] == partial_id)
    assert partial["status"] == "in_progress"
    assert partial["plan"][0]["done"] is True
    assert partial["plan"][1]["done"] is False
    assert "Частично выполнено коммитами" in partial["report"]
    assert job["stats"]["tasks_partial"] == 1
    assert job["stats"]["plan_steps_marked"] == 1

    # список репозиториев с ветками — для модалки настройки
    r = await user_client.get(f"/api/projects/{pid}/git/repos")
    repos = r.json()
    service = next(x for x in repos if x["path"] == "service")
    assert service["total_commits"] == 2
    assert service["current_branch"] in service["branches"] or service["branches"] == []

    # повторный импорт с per-repo конфигом (ветка/период/лимит) не плодит дубликаты
    r = await user_client.post(
        f"/api/projects/{pid}/git/import",
        json={
            "repos": [
                {
                    "path": "service",
                    "branch": service["current_branch"],
                    "since_days": 3650,
                    "limit": 50,
                }
            ]
        },
    )
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["stats"]["repos"] == 1
    assert job["stats"]["commits_new"] == 0
