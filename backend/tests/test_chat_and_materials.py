from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest_asyncio

from .conftest import latest_job, wait_job


@pytest_asyncio.fixture
async def project(user_client: httpx.AsyncClient, sample_project_dir: Path) -> dict:
    r = await user_client.post(
        "/api/projects", json={"name": "Чат-проект", "root_path": str(sample_project_dir)}
    )
    project = r.json()
    job = await latest_job(user_client, project["id"], "index")
    await wait_job(user_client, project["id"], job["id"])
    return project


def parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


async def test_chat_stream_and_persistence(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]

    r = await user_client.post(f"/api/projects/{pid}/chats", json={})
    assert r.status_code == 201
    chat = r.json()
    assert chat["model"] == "opus"  # Opus 5 по умолчанию
    assert chat["reasoning"] == "high"

    # смена модели/резонинга
    r = await user_client.patch(
        f"/api/projects/{pid}/chats/{chat['id']}", json={"model": "sonnet", "reasoning": "low"}
    )
    assert r.json()["model"] == "sonnet"
    r = await user_client.patch(f"/api/projects/{pid}/chats/{chat['id']}", json={"model": "gpt"})
    assert r.status_code == 400

    # отправка сообщения — SSE-стрим (фейковый claude)
    r = await user_client.post(
        f"/api/projects/{pid}/chats/{chat['id']}/messages",
        json={"content": "Расскажи о проекте"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    events = parse_sse(r.text)
    types = [e["type"] for e in events]
    assert "delta" in types and "done" in types
    assert any(e["type"] == "tool" for e in events)  # tool_use дошёл до клиента
    text = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "Тестовый ответ" in text

    # сообщения сохранились, сессия запомнилась
    r = await user_client.get(f"/api/projects/{pid}/chats/{chat['id']}/messages")
    msgs = r.json()
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant"]
    assert msgs[1]["meta"]["cost_usd"] == 0.001

    r = await user_client.get(f"/api/projects/{pid}/chats")
    assert r.json()[0]["title"].startswith("Расскажи о проекте")


async def test_clarifying_material_updates_existing_tasks(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    """Созвон даёт скелет задач, а ТЗ, пришедшее позже, — логику, без которой их
    не сделать. Уточнение обязано доехать до уже заведённой задачи, а не потеряться
    как дубликат и не задвоить доску."""
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/materials",
        files={"file": ("call.txt", "Созвон про фичу А.".encode("utf-8"), "text/plain")},
    )
    call = r.json()
    job = await latest_job(user_client, pid, "process_material")
    await wait_job(user_client, pid, job["id"])

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    feature = next(t for t in r.json() if t["title"] == "Сделать фичу А")
    assert feature["extra"]["from_material"]["id"] == call["id"], "задача помнит свой материал"

    # ТЗ загружается как уточнение к созвону
    r = await user_client.post(
        f"/api/projects/{pid}/materials?clarifies={call['id']}",
        files={"file": ("tz.txt", "Логика девяти игроков.".encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201, r.text
    spec = r.json()
    assert spec["meta"]["clarifies"] == call["id"]
    job = await latest_job(user_client, pid, "process_material")
    job = await wait_job(user_client, pid, job["id"])
    assert job["status"] == "done", job
    assert job["stats"]["tasks_updated"] == 1, job["stats"]
    assert job["stats"]["tasks_created"] == 1, job["stats"]

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    tasks = r.json()
    assert sum(1 for t in tasks if t["title"] == "Сделать фичу А") == 1, "задача не задвоилась"
    feature = next(t for t in tasks if t["title"] == "Сделать фичу А")
    clar = feature["extra"]["clarifications"]
    assert len(clar) == 1, clar
    assert "девяти игроков" in clar[0]["text"], "логика из ТЗ обязана доехать"
    assert clar[0]["source"] == "tz.txt", "видно, откуда уточнение"
    assert feature["extra"]["enriched"] is False, "досье собрано по старому тексту — переработать"
    assert feature["extra"]["updated_by_materials"][0]["filename"] == "tz.txt"

    # уточнение переживает проработку: она пересобирает description целиком,
    # и лежи оно там — затёрлось бы
    r = await user_client.post(f"/api/projects/{pid}/tasks/{feature['id']}/enrich")
    await wait_job(user_client, pid, r.json()["job_id"])
    r = await user_client.get(f"/api/projects/{pid}/tasks")
    feature = next(t for t in r.json() if t["title"] == "Сделать фичу А")
    assert feature["extra"]["enriched"] is True
    assert "девяти игроков" in feature["extra"]["clarifications"][0]["text"]

    # промах по названию не роняет обработку и не создаёт мусор
    assert not any(t["title"] == "Задачи с таким названием нет" for t in tasks)


async def test_note_is_a_material(user_client: httpx.AsyncClient, project: dict) -> None:
    """Свой текст — такой же материал: отдельной механики под него нет."""
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/materials/note",
        json={"title": "Мысли по фиче", "text": "Своими словами: нужно учесть вот это."},
    )
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["media_type"] == "text/plain"
    job = await latest_job(user_client, pid, "process_material")
    job = await wait_job(user_client, pid, job["id"])
    assert job["status"] == "done", job
    r = await user_client.get(f"/api/projects/{pid}/materials/{note['id']}/text")
    assert "Своими словами" in r.json()["text"]

    r = await user_client.post(
        f"/api/projects/{pid}/materials/note",
        json={"text": "x", "clarifies": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 400, "битая ссылка на материал должна отлетать сразу"


async def test_material_upload_creates_tasks(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    content = "Созвон: обсудили фичу А и баг Б. Решили делать.".encode("utf-8")
    r = await user_client.post(
        f"/api/projects/{pid}/materials",
        files={"file": ("meeting_notes.txt", content, "text/plain")},
    )
    assert r.status_code == 201, r.text
    material = r.json()

    job = await latest_job(user_client, pid, "process_material")
    job = await wait_job(user_client, pid, job["id"])
    assert job["status"] == "done", job
    assert job["stats"]["tasks_created"] == 2  # фейковый claude извлекает 2 задачи

    r = await user_client.get(f"/api/projects/{pid}/materials")
    m = next(x for x in r.json() if x["id"] == material["id"])
    assert m["status"] == "ready"
    assert m["summary"]

    r = await user_client.get(f"/api/projects/{pid}/materials/{material['id']}/text")
    assert "Созвон" in r.json()["text"]

    # задачи из материала попали в канбан с источником doc
    r = await user_client.get(f"/api/projects/{pid}/tasks")
    tasks = r.json()
    titles = {t["title"] for t in tasks}
    assert "Сделать фичу А" in titles and "Починить баг Б" in titles
    assert all(t["source"] == "doc" for t in tasks if t["title"] in ("Сделать фичу А", "Починить баг Б"))

    # RLM-запрос (фейковый план + под-вызов)
    r = await user_client.post(
        f"/api/projects/{pid}/ask", json={"question": "Как устроен проект?"}
    )
    assert r.status_code == 200
    assert r.json()["answer"]
