"""Мультирепо-проекты: добавление второго каталога, индексация с префиксом
алиаса, удаление с очисткой реестра/графа/векторов."""

from __future__ import annotations

import httpx

from .conftest import wait_job


async def _create_project(user_client: httpx.AsyncClient, path, name: str) -> str:
    r = await user_client.post("/api/projects", json={"name": name, "root_path": str(path)})
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]
    jobs = (await user_client.get(f"/api/projects/{project_id}/jobs")).json()
    index_jobs = [j for j in jobs if j["type"] == "index"]
    assert index_jobs, "первичная индексация не запустилась"
    job = await wait_job(user_client, project_id, index_jobs[0]["id"])
    assert job["status"] == "done", job
    return project_id


async def test_multiroot_add_index_remove(
    user_client: httpx.AsyncClient, sample_project_dir, tmp_path_factory
):
    project_id = await _create_project(user_client, sample_project_dir, "Мультирепо-проект")

    second = tmp_path_factory.mktemp("secondrepo")
    (second / "api.py").write_text("def api():\n    return 'ok'\n", encoding="utf-8")
    (second / "README.md").write_text("# Второй репозиторий\n", encoding="utf-8")

    # добавление каталога сразу запускает инкрементальную индексацию
    r = await user_client.post(
        f"/api/projects/{project_id}/roots", json={"path": str(second)}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    alias = data["alias"]
    assert alias and data["job_id"], data
    job = await wait_job(user_client, project_id, data["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["scan"]["added"] >= 2, job["stats"]

    # каталог сохранён в meta проекта
    r = await user_client.get(f"/api/projects/{project_id}")
    extras = r.json()["meta"].get("extra_roots") or []
    assert [e["alias"] for e in extras] == [alias]

    # файлы второго корня в реестре с префиксом алиаса и проанализированы
    r = await user_client.get(
        f"/api/projects/{project_id}/files", params={"q": f"{alias}/"}
    )
    items = r.json()["items"]
    target = next((i for i in items if i["rel_path"] == f"{alias}/api.py"), None)
    assert target is not None, items
    assert target["analysis_status"] == "analyzed"
    assert "api.py" in (target["summary"] or "")

    # граф и вектора знают файл по префиксованному пути
    r = await user_client.get(
        f"/api/projects/{project_id}/graph/file", params={"path": f"{alias}/api.py"}
    )
    assert r.status_code == 200, r.text

    from app.services import vectors

    hits = await vectors.search(project_id, "делает тестовые вещи", limit=20)
    assert any(h["key"] == f"{alias}/api.py" for h in hits), hits

    # тот же каталог второй раз не добавляется
    r = await user_client.post(
        f"/api/projects/{project_id}/roots", json={"path": str(second)}
    )
    assert r.status_code == 409

    # удаление корня чистит реестр, граф и вектора
    r = await user_client.delete(f"/api/projects/{project_id}/roots/{alias}")
    assert r.status_code == 200
    assert r.json()["extra_roots"] == []

    r = await user_client.get(
        f"/api/projects/{project_id}/files", params={"q": f"{alias}/"}
    )
    assert r.json()["total"] == 0
    r = await user_client.get(
        f"/api/projects/{project_id}/graph/file", params={"path": f"{alias}/api.py"}
    )
    assert r.status_code == 404
    hits = await vectors.search(project_id, "делает тестовые вещи", limit=20)
    assert not any(h["key"].startswith(f"{alias}/") for h in hits), hits
