"""Дублирование проекта и полнота удаления.

Ключевое требование к дублю: он физически независим (своя БД-строка, свой
подграф, свои вектора), поэтому удаление оригинала его не задевает — и при этом
файлы приезжают уже проанализированными, чтобы не платить за ИИ-разбор дважды.
"""

from __future__ import annotations

import httpx

from .conftest import wait_job


async def _ready_project(user_client: httpx.AsyncClient, path, name: str) -> str:
    r = await user_client.post("/api/projects", json={"name": name, "root_path": str(path)})
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]
    jobs = (await user_client.get(f"/api/projects/{project_id}/jobs")).json()
    index_job = next(j for j in jobs if j["type"] == "index")
    job = await wait_job(user_client, project_id, index_job["id"])
    assert job["status"] == "done", job
    return project_id


async def test_duplicate_is_independent_and_skips_reanalysis(
    user_client: httpx.AsyncClient, sample_project_dir
):
    from app.services import vectors

    original = await _ready_project(user_client, sample_project_dir, "Оригинал")

    # немного состояния, которое должно переехать в копию
    r = await user_client.post(
        f"/api/projects/{original}/tasks",
        json={"title": "Починить оплату", "description": "подробности"},
    )
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]
    await user_client.post(
        f"/api/projects/{original}/decisions",
        json={"topic": "Роли", "text": "ORGANIZER упразднена, теперь MANAGER"},
    )

    files_before = (await user_client.get(f"/api/projects/{original}/files")).json()
    assert files_before["total"] > 0
    analyzed_before = {
        f["rel_path"]: f["analysis_status"] for f in files_before["items"]
    }
    assert "analyzed" in analyzed_before.values()

    r = await user_client.post(f"/api/projects/{original}/duplicate", json={})
    assert r.status_code == 201, r.text
    copy = r.json()
    copy_id = copy["id"]
    assert copy_id != original
    assert copy["name"] == "Оригинал — копия"

    # копия смотрит в тот же каталог, но наблюдение за ним выключено:
    # два вотчера на один каталог задваивали бы индексацию
    detail = (await user_client.get(f"/api/projects/{copy_id}")).json()
    assert detail["root_path"] == str(sample_project_dir)
    assert detail["meta"]["watch"] is False
    assert detail["meta"]["duplicated_from"] == original
    assert "service_token" not in detail["meta"]  # наружу не отдаётся

    # файлы приехали уже разобранными — переанализ не потребуется
    files_copy = (await user_client.get(f"/api/projects/{copy_id}/files")).json()
    assert files_copy["total"] == files_before["total"]
    assert {f["rel_path"]: f["analysis_status"] for f in files_copy["items"]} == analyzed_before
    assert all(f["analysis_status"] != "pending" for f in files_copy["items"])

    # задачи и соглашения — с новыми id
    tasks_copy = (await user_client.get(f"/api/projects/{copy_id}/tasks")).json()
    assert [t["title"] for t in tasks_copy] == ["Починить оплату"]
    assert tasks_copy[0]["id"] != task_id
    decisions_copy = (await user_client.get(f"/api/projects/{copy_id}/decisions")).json()
    assert [d["topic"] for d in decisions_copy] == ["Роли"]

    # карта знаний и вектора у копии свои
    r = await user_client.get(
        f"/api/projects/{copy_id}/graph/file", params={"path": "main.py"}
    )
    assert r.status_code == 200, r.text
    assert await vectors.search(copy_id, "делает тестовые вещи", limit=20)

    # --- удаление оригинала не должно задеть копию ---
    assert (await user_client.delete(f"/api/projects/{original}")).status_code == 204
    assert (await user_client.get(f"/api/projects/{original}")).status_code == 404

    r = await user_client.get(f"/api/projects/{copy_id}/files")
    assert r.json()["total"] == files_before["total"]
    r = await user_client.get(
        f"/api/projects/{copy_id}/graph/file", params={"path": "main.py"}
    )
    assert r.status_code == 200, "граф копии умер вместе с оригиналом"
    assert await vectors.search(copy_id, "делает тестовые вещи", limit=20), "вектора копии пропали"
    assert (await user_client.get(f"/api/projects/{copy_id}/tasks")).json()


async def test_duplicate_names_do_not_collide(user_client: httpx.AsyncClient, sample_project_dir):
    """Каталог плагина ключуется по слагу имени — одинаковые имена перетирали бы
    друг друга, поэтому второй дубль обязан получить другое имя."""
    original = await _ready_project(user_client, sample_project_dir, "Дубль-тест")
    first = (await user_client.post(f"/api/projects/{original}/duplicate", json={})).json()
    second = (await user_client.post(f"/api/projects/{original}/duplicate", json={})).json()
    assert first["name"] == "Дубль-тест — копия"
    assert second["name"] == "Дубль-тест — копия 2"

    named = (
        await user_client.post(
            f"/api/projects/{original}/duplicate", json={"name": "Своё имя"}
        )
    ).json()
    assert named["name"] == "Своё имя"


async def test_plugin_installs_into_project_only(
    user_client: httpx.AsyncClient, sample_project_dir
):
    """Плагин должен включаться в `<проект>/.claude/settings.local.json`, а не
    глобально в ~/.claude — и не затирать то, что пользователь уже там настроил."""
    import json
    from pathlib import Path

    project_id = await _ready_project(user_client, sample_project_dir, "Локальный плагин")

    settings_path = Path(sample_project_dir) / ".claude" / "settings.local.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"permissions": {"allow": ["Bash(npm test)"]}}), encoding="utf-8"
    )

    info = (await user_client.get(f"/api/projects/{project_id}/plugin")).json()
    assert info["installed_locally"] is False
    assert info["local_settings_path"] == str(settings_path)

    r = await user_client.post(f"/api/projects/{project_id}/plugin/local")
    assert r.status_code == 200, r.text

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    key = f"{info['slug']}@projectai"
    assert data["enabledPlugins"][key] is True
    assert data["extraKnownMarketplaces"]["projectai"]["source"]["source"] == "directory"
    assert data["permissions"] == {"allow": ["Bash(npm test)"]}, "чужие ключи затёрлись"

    info = (await user_client.get(f"/api/projects/{project_id}/plugin")).json()
    assert info["installed_locally"] is True

    # снятие тоже не должно уносить чужое
    r = await user_client.delete(f"/api/projects/{project_id}/plugin/local")
    assert r.status_code == 200 and r.json()["removed"] is True
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "enabledPlugins" not in data
    assert data["permissions"] == {"allow": ["Bash(npm test)"]}


async def test_delete_project_cleans_plugin_and_mcp_config(
    user_client: httpx.AsyncClient, sample_project_dir
):
    """Плагин и mcp-конфиг лежат вне каталога проекта: после удаления они не
    должны остаться на диске и в marketplace.json."""
    import json
    import uuid
    from pathlib import Path

    from app.config import get_settings
    from app.services import plugin_gen

    project_id = await _ready_project(user_client, sample_project_dir, "Проект с плагином")

    r = await user_client.post(f"/api/projects/{project_id}/plugin/regenerate")
    job = await wait_job(user_client, project_id, r.json()["job_id"])
    assert job["status"] == "done", job

    info = (await user_client.get(f"/api/projects/{project_id}/plugin")).json()
    plugin_dir = Path(info["path"])
    assert plugin_dir.is_dir(), info

    # mcp-конфиг чата пишется файлом data/mcp/<id>.json
    mcp_path = Path(await plugin_gen.get_chat_mcp_config(uuid.UUID(project_id)))
    assert mcp_path.is_file()

    assert (await user_client.delete(f"/api/projects/{project_id}")).status_code == 204

    assert not plugin_dir.exists(), "каталог плагина удалённого проекта остался"
    assert not mcp_path.exists(), "mcp-конфиг удалённого проекта остался"

    marketplace = get_settings().data_path / "plugins" / ".claude-plugin" / "marketplace.json"
    if marketplace.is_file():
        names = [p["name"] for p in json.loads(marketplace.read_text(encoding="utf-8"))["plugins"]]
        assert info["slug"] not in names, "удалённый проект остался в marketplace.json"
