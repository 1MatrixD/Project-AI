"""Векторный поиск (Qdrant): эмбеддинги в индексации, гибридный /graph/search,
очистка при удалении проекта. Эмбеддер фейковый (EMBED_FAKE=1, bag-of-words)."""

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


async def test_semantic_search_after_index(user_client: httpx.AsyncClient, sample_project_dir):
    project_id = await _create_project(user_client, sample_project_dir, "Вектор-проект")

    # вектора файлов записались при ИИ-анализе
    from app.services import vectors

    hits = await vectors.search(project_id, "делает тестовые вещи", limit=10)
    assert hits, "семантический поиск не нашёл проанализированные файлы"
    assert any(h["kind"] == "file" and h["key"] == "main.py" for h in hits), hits

    # гибридный поиск: фулл-текст и семантика вместе, у хитов есть match
    r = await user_client.get(
        f"/api/projects/{project_id}/graph/search", params={"q": "делает тестовые вещи"}
    )
    assert r.status_code == 200, r.text
    results = r.json()
    assert results
    assert all(h.get("match") in ("fulltext", "semantic", "both") for h in results), results
    # совпадение и по тексту, и по смыслу → main.py помечен both
    main_hits = [h for h in results if h.get("path") == "main.py"]
    assert main_hits and main_hits[0]["match"] in ("both", "semantic"), results

    # запрос без общих слов с выжимками — семантических хитов нет (фейковый эмбеддер)
    nothing = await vectors.search(project_id, "квантовая гравитация чёрных дыр", limit=5)
    assert nothing == []


async def test_decision_vectors_and_project_cleanup(
    user_client: httpx.AsyncClient, sample_project_dir
):
    project_id = await _create_project(user_client, sample_project_dir, "Вектор-очистка")

    r = await user_client.post(
        f"/api/projects/{project_id}/decisions",
        json={"topic": "Хранение паролей", "text": "Пароли храним только в bcrypt-хэшах."},
    )
    assert r.status_code == 201, r.text
    decision_id = r.json()["id"]

    from app.services import vectors

    hits = await vectors.search(project_id, "пароли bcrypt хранение", limit=5)
    assert any(h["kind"] == "decision" for h in hits), hits

    # удаление соглашения убирает его вектор
    r = await user_client.delete(f"/api/projects/{project_id}/decisions/{decision_id}")
    assert r.status_code == 204
    hits = await vectors.search(project_id, "пароли bcrypt хранение", limit=5)
    assert not any(h["kind"] == "decision" for h in hits), hits

    # удаление проекта чистит все его вектора
    r = await user_client.delete(f"/api/projects/{project_id}")
    assert r.status_code == 204
    assert await vectors.search(project_id, "делает тестовые вещи", limit=5) == []
