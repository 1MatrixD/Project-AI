from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from .conftest import wait_job


async def test_register_login_me(client: httpx.AsyncClient) -> None:
    email = f"a-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 200
    token = r.json()["token"]

    r = await client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 409  # дубликат

    r = await client.post("/api/auth/login", json={"email": email, "password": "wrong-pass"})
    assert r.status_code == 401

    r = await client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200

    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == email


async def test_project_lifecycle_with_index(user_client: httpx.AsyncClient, sample_project_dir: Path) -> None:
    # создание проекта сразу запускает первичную индексацию (фейковый claude)
    r = await user_client.post(
        "/api/projects",
        json={"name": "Тест-проект", "root_path": str(sample_project_dir), "description": "описание"},
    )
    assert r.status_code == 201, r.text
    project = r.json()
    pid = project["id"]
    assert project["status"] == "created"

    r = await user_client.get(f"/api/projects/{pid}/jobs")
    job = next(j for j in r.json() if j["type"] == "index")
    job = await wait_job(user_client, pid, job["id"])
    assert job["status"] == "done", job
    assert job["stats"]["scan"]["added"] >= 4

    # проект готов, meta заполнена, сервисный токен скрыт
    r = await user_client.get(f"/api/projects/{pid}")
    detail = r.json()
    assert detail["status"] == "ready"
    assert "service_token" not in detail["meta"]
    assert detail["meta"]["stats"]["files_total"] >= 4
    assert detail["meta"]["overview"]["summary"]  # синтез прошёл

    # файлы проанализированы фейковым ИИ
    r = await user_client.get(f"/api/projects/{pid}/files")
    files = r.json()
    assert files["total"] >= 4
    analyzed = [f for f in files["items"] if f["analysis_status"] == "analyzed"]
    assert analyzed, files

    # отчёт об изменениях
    r = await user_client.get(f"/api/projects/{pid}/changes")
    changes = r.json()
    assert changes and changes[0]["stats"]["added"] >= 4

    # инкрементальное обновление: меняем файл
    (sample_project_dir / "main.py").write_text("def main():\n    print('v2')\n", encoding="utf-8")
    (sample_project_dir / "extra.py").write_text("x = 1\n", encoding="utf-8")
    r = await user_client.post(f"/api/projects/{pid}/index", json={"mode": "update"})
    assert r.status_code == 200, r.text
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["stats"]["scan"]["added"] == 1
    assert job["stats"]["scan"]["modified"] == 1

    # карта знаний наполнена
    r = await user_client.get(f"/api/projects/{pid}/graph")
    g = r.json()
    assert any("File" in n["labels"] for n in g["nodes"])
    assert any("Entity" in n["labels"] for n in g["nodes"])

    # cypher read-only
    r = await user_client.post(
        f"/api/projects/{pid}/graph/cypher",
        json={"query": "MATCH (f:File {project_id: $pid}) RETURN f.path AS path LIMIT 5"},
    )
    assert r.status_code == 200 and r.json()

    r = await user_client.post(
        f"/api/projects/{pid}/graph/cypher",
        json={"query": "MATCH (n) DETACH DELETE n"},
    )
    assert r.status_code == 400  # запись запрещена

    # плагин сгенерирован; сценарные скиллы на месте
    r = await user_client.get(f"/api/projects/{pid}/plugin")
    info = r.json()
    assert info["exists"], info
    skills_dir = Path(info["path"]) / "skills"
    for name in ("architecture", "project-workflow", "task-briefing", "how-to-search"):
        assert (skills_dir / name / "SKILL.md").is_file(), name
    workflow = (skills_dir / "project-workflow" / "SKILL.md").read_text(encoding="utf-8")
    assert "record_decision" in workflow, "workflow-скилл обязан учить фиксировать соглашения"
    assert "суб-агент" not in workflow, "обновление карты теперь ручное — скилл не должен обещать автозапуск"

    # удаление
    r = await user_client.delete(f"/api/projects/{pid}")
    assert r.status_code == 204


async def test_project_access_isolation(user_client: httpx.AsyncClient, sample_project_dir: Path, client: httpx.AsyncClient) -> None:
    r = await user_client.post(
        "/api/projects", json={"name": "Приватный", "root_path": str(sample_project_dir)}
    )
    pid = r.json()["id"]

    email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    r2 = await client.post("/api/auth/register", json={"email": email, "password": "secret123"})
    other_token = r2.json()["token"]
    r3 = await client.get(
        f"/api/projects/{pid}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert r3.status_code == 403


async def test_fs_endpoints(user_client: httpx.AsyncClient, tmp_path: Path) -> None:
    r = await user_client.get("/api/fs/drives")
    assert r.status_code == 200 and r.json()
    r = await user_client.get("/api/fs/list", params={"path": str(tmp_path)})
    assert r.status_code == 200
    assert r.json()["path"] == str(tmp_path)

