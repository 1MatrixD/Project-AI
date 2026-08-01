"""Планировщик (декомпозиция с зависимостями) и watchdog-наблюдение за каталогом."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from .conftest import latest_job, wait_job


async def _create_project(user_client: httpx.AsyncClient, path: Path, name: str) -> str:
    r = await user_client.post("/api/projects", json={"name": name, "root_path": str(path)})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    job = await latest_job(user_client, pid, "index")
    await wait_job(user_client, pid, job["id"])
    return pid


async def test_planner_decomposes_task_with_dependencies(
    user_client: httpx.AsyncClient, sample_project_dir: Path
) -> None:
    pid = await _create_project(user_client, sample_project_dir, "Планировщик")

    r = await user_client.post(
        f"/api/projects/{pid}/tasks", json={"title": "Большая фича с созвона"}
    )
    task_id = r.json()["id"]

    r = await user_client.post(f"/api/projects/{pid}/tasks/{task_id}/plan")
    assert r.status_code == 200, r.text
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["subtasks"] == 3

    tasks = (await user_client.get(f"/api/projects/{pid}/tasks")).json()
    subs = [t for t in tasks if t["source"] == "plan"]
    assert len(subs) == 3
    by_title = {t["title"]: t for t in subs}
    model_task = by_title["Подзадача: модель и миграция"]
    api_task = by_title["Подзадача: API-эндпоинт"]
    front_task = by_title["Подзадача: экран на фронте"]

    # индексы depends_on разрешены в реальные id; мусорные (self, за пределами) отброшены
    assert model_task["extra"]["depends_on"] == []
    assert api_task["extra"]["depends_on"] == [model_task["id"]]
    assert front_task["extra"]["depends_on"] == [api_task["id"]]
    assert api_task["extra"]["parent_task"] == task_id
    assert api_task["extra"]["parent_title"] == "Большая фича с созвона"
    assert api_task["status"] == "planned"
    assert [p["text"] for p in api_task["plan"]] == ["хендлер", "тест"]

    # родительская задача знает общий план и подзадачи
    parent = next(t for t in tasks if t["id"] == task_id)
    assert parent["extra"]["planned"] is True
    assert set(parent["extra"]["subtasks"]) == {t["id"] for t in subs}
    assert "модель данных" in parent["extra"]["plan_summary"]


async def test_watch_triggers_incremental_index(
    user_client: httpx.AsyncClient, sample_project_dir: Path
) -> None:
    pid = await _create_project(user_client, sample_project_dir, "Наблюдение")

    r = await user_client.post(f"/api/projects/{pid}/watch", json={"enabled": True})
    assert r.status_code == 200 and r.json()["watch"] is True
    prev = await latest_job(user_client, pid, "index")

    # правим файл — watcher после дебаунса сам запускает обновление индекса
    (sample_project_dir / "main.py").write_text(
        "def main():\n    print('changed by watch test')\n", encoding="utf-8"
    )

    new_job = None
    deadline = asyncio.get_event_loop().time() + 25
    while asyncio.get_event_loop().time() < deadline:
        j = await latest_job(user_client, pid, "index")
        if j and j["id"] != prev["id"]:
            new_job = j
            break
        await asyncio.sleep(0.3)
    assert new_job is not None, "watch не запустил обновление индекса"
    job = await wait_job(user_client, pid, new_job["id"])
    assert job["status"] == "done", job
    assert job["stats"]["scan"]["modified"] == 1

    # выключение: наблюдение снимается и состояние сохраняется в meta
    r = await user_client.post(f"/api/projects/{pid}/watch", json={"enabled": False})
    assert r.json()["watch"] is False
    detail = (await user_client.get(f"/api/projects/{pid}")).json()
    assert detail["meta"]["watch"] is False
