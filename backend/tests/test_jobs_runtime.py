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
