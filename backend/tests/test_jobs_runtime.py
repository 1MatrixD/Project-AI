"""SSE-события, отмена задач, автопродолжение анализа."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest_asyncio

from .conftest import latest_job, wait_job


@pytest_asyncio.fixture
async def project(user_client: httpx.AsyncClient, sample_project_dir: Path) -> dict:
    r = await user_client.post(
        "/api/projects", json={"name": "Runtime-проект", "root_path": str(sample_project_dir)}
    )
    project = r.json()
    job = await latest_job(user_client, project["id"], "index")
    await wait_job(user_client, project["id"], job["id"])
    return project


def _parse_events(sse_text: str) -> list[dict]:
    events = []
    for line in sse_text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


async def test_sse_stream_pushes_job_and_task_events(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    pid = project["id"]

    # ASGITransport буферизует ответ, поэтому просим сервер закрыть поток сам
    collect = asyncio.create_task(
        user_client.get(f"/api/projects/{pid}/jobs/events", params={"lifetime": 6})
    )
    await asyncio.sleep(0.4)  # подписка успела встать

    # источники событий: фоновая задача + изменение канбана
    r = await user_client.post(f"/api/projects/{pid}/index", json={"mode": "update"})
    job_id = r.json()["job_id"]
    await wait_job(user_client, pid, job_id)
    await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Задача для события"})

    resp = await asyncio.wait_for(collect, timeout=30)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_events(resp.text)

    job_events = [e for e in events if e.get("type") == "job" and e["job"]["id"] == job_id]
    statuses = [e["job"]["status"] for e in job_events]
    assert "done" in statuses, f"нет события о завершении: {events}"
    assert any(s in ("queued", "running") for s in statuses)
    assert any(e.get("type") == "tasks_changed" for e in events)


async def test_cancel_running_job(user_client: httpx.AsyncClient, project: dict) -> None:
    import uuid as uuid_mod

    from app.jobs_runner import runner

    started = asyncio.Event()

    async def slow_handler(job_id, project_id, params):
        started.set()
        for _ in range(200):  # ~10 секунд, если не отменят
            runner.check_cancelled(job_id)
            await asyncio.sleep(0.05)
        return {"finished": True}

    runner.register("slow_test", slow_handler)
    job = await runner.submit(uuid_mod.UUID(project["id"]), "slow_test", {})
    await asyncio.wait_for(started.wait(), timeout=10)

    r = await user_client.post(f"/api/projects/{project['id']}/jobs/{job.id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelling"

    final = await wait_job(user_client, project["id"], str(job.id))
    assert final["status"] == "cancelled"
    assert final["detail"] == "Отменено пользователем"

    # повторная отмена завершённой задачи — 409
    r = await user_client.post(f"/api/projects/{project['id']}/jobs/{job.id}/cancel")
    assert r.status_code == 409


async def test_auto_continue_backlog(
    user_client: httpx.AsyncClient, sample_project_dir: Path
) -> None:
    # 14 анализируемых файлов; первичная индексация возьмёт 10 (лимит из env),
    # хвост добьют автопродолжения порциями по 2
    for i in range(10):
        (sample_project_dir / f"mod_{i:02d}.py").write_text(f"x = {i}\n", encoding="utf-8")
    r = await user_client.post(
        "/api/projects", json={"name": "Бэклог-проект", "root_path": str(sample_project_dir)}
    )
    pid = r.json()["id"]
    job = await latest_job(user_client, pid, "index")
    await wait_job(user_client, pid, job["id"])

    r = await user_client.post(
        f"/api/projects/{pid}/index",
        json={"mode": "update", "ai_limit": 2, "auto_continue": True},
    )
    first = await wait_job(user_client, pid, r.json()["job_id"])
    assert first["status"] == "done"
    assert first["stats"].get("auto_continued") is True, first["stats"]

    # ждём, пока цепочка сама доберёт бэклог до нуля
    deadline = asyncio.get_event_loop().time() + 60
    while True:
        r = await user_client.get(f"/api/projects/{pid}/jobs", params={"limit": 50})
        index_jobs = [j for j in r.json() if j["type"] == "index"]
        if not any(j["status"] in ("queued", "running") for j in index_jobs):
            break
        assert asyncio.get_event_loop().time() < deadline, "цепочка не завершилась"
        await asyncio.sleep(0.3)

    last = index_jobs[0]  # список отсортирован по created_at desc
    assert last["status"] == "done"
    assert last["stats"]["ai"]["pending_left"] == 0
    assert not last["stats"].get("auto_continued")
    assert len(index_jobs) >= 3  # initial + ручной + минимум одно автопродолжение
