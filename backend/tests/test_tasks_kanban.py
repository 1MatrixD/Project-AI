from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest_asyncio

from .conftest import latest_job, wait_job


@pytest_asyncio.fixture
async def project(user_client: httpx.AsyncClient, sample_project_dir: Path) -> dict:
    r = await user_client.post(
        "/api/projects", json={"name": "Канбан-проект", "root_path": str(sample_project_dir)}
    )
    assert r.status_code == 201
    project = r.json()
    job = await latest_job(user_client, project["id"], "index")
    await wait_job(user_client, project["id"], job["id"])
    return project


async def test_deleted_task_leaves_no_trace_in_graph(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    """Удалённая задача не должна оставаться в карте знаний: её находил поиск,
    а связи AFFECTS с файлами подсказывали проработке соседних задач."""
    pid = project["id"]
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Задача на снос"})
    task_id = r.json()["id"]
    # связь с файлом появляется при отчёте о выполнении
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/{task_id}/done",
        json={"report": "сделано", "files": ["main.py"]},
    )
    assert r.status_code == 200, r.text

    async def graph_rows(query: str) -> list:
        res = await user_client.post(f"/api/projects/{pid}/graph/cypher", json={"query": query})
        assert res.status_code == 200, res.text
        return res.json()

    node_q = "MATCH (t:Task {project_id: $pid}) WHERE t.title = 'Задача на снос' RETURN t.title AS title"
    edge_q = (
        "MATCH (t:Task {project_id: $pid})-[:AFFECTS]->(f:File) "
        "WHERE t.title = 'Задача на снос' RETURN f.path AS path"
    )
    assert await graph_rows(node_q), "узел задачи должен быть в графе до удаления"
    assert await graph_rows(edge_q), "связь с файлом должна быть в графе до удаления"

    r = await user_client.delete(f"/api/projects/{pid}/tasks/{task_id}")
    assert r.status_code == 204
    assert await graph_rows(node_q) == [], "узел задачи остался в карте знаний"
    assert await graph_rows(edge_q) == [], "связь с файлом пережила удаление задачи"


async def test_index_prunes_orphan_task_nodes(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    """Узел задачи может пережить удаление, если граф в тот момент был недоступен.
    Обновление индекса подметает такие сироты: их заголовок — формулировка задачи,
    поэтому они попадают в полнотекстовую выдачу и отъедают места у файлов,
    по которым RLM выбирает, что читать."""
    from app.services import graphdb

    pid = project["id"]
    await graphdb.upsert_task_node(
        pid, str(uuid.uuid4()), "Призрак удалённой задачи", "planned", ["main.py"]
    )
    q = (
        "MATCH (t:Task {project_id: $pid}) WHERE t.title = 'Призрак удалённой задачи' "
        "RETURN t.title AS title"
    )

    async def ghosts() -> list:
        r = await user_client.post(f"/api/projects/{pid}/graph/cypher", json={"query": q})
        assert r.status_code == 200, r.text
        return r.json()

    assert await ghosts(), "узел-призрак должен существовать до обновления индекса"

    r = await user_client.post(f"/api/projects/{pid}/index", json={"mode": "update"})
    assert r.status_code == 200, r.text
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["orphan_tasks_removed"] >= 1, job["stats"]
    assert await ghosts() == [], "сирота пережил обновление индекса"


async def test_long_task_text_goes_into_description(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    """Формулировка задачи бывает длиннее 300 символов. title остаётся коротким
    заголовком карточки, а полный текст едет в description — и не режется."""
    pid = project["id"]
    long_text = (
        "Хочу переделать выбор каталога при создании проекта. "
        "Сейчас это самописная модалка, а хочется системный диалог Windows. " * 12
    )
    assert len(long_text) > 300

    r = await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": long_text[:120] + "…", "description": long_text},
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["description"] == long_text
    assert len(task["title"]) <= 300

    # заголовок длиннее 300 по-прежнему отвергается — это подпись, а не текст
    r = await user_client.post(
        f"/api/projects/{pid}/tasks", json={"title": long_text}
    )
    assert r.status_code == 422

    # промпты проработки берут текст задачи целиком, а не первые 2000 символов
    from app.services.prompts import TASK_TEXT_LIMIT

    assert TASK_TEXT_LIMIT >= 8000


async def test_kanban_flow(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]

    r = await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Первая задача", "description": "описание", "plan": ["шаг"]},
    )
    assert r.status_code == 201
    t1 = r.json()
    assert t1["status"] == "planned" and t1["source"] == "manual"

    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Вторая задача"})
    t2 = r.json()

    # улучшение описания (как это делает ИИ через MCP)
    r = await user_client.patch(
        f"/api/projects/{pid}/tasks/{t1['id']}",
        json={"description": "уточнённое описание", "plan": ["шаг 1", "шаг 2"]},
    )
    assert r.json()["description"] == "уточнённое описание"

    # перенос колонки
    r = await user_client.patch(f"/api/projects/{pid}/tasks/{t1['id']}", json={"status": "in_progress"})
    assert r.json()["status"] == "in_progress"

    r = await user_client.patch(f"/api/projects/{pid}/tasks/{t1['id']}", json={"status": "bogus"})
    assert r.status_code == 400

    # reorder
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/reorder",
        json={"status": "planned", "ordered_ids": [t2["id"]]},
    )
    assert r.status_code == 200

    # done с отчётом → worklog копится; карта обновляется ВРУЧНУЮ — автозапуск
    # после каждой задачи конкурировал за ИИ-слоты с проработками при пакетной работе
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/{t1['id']}/done",
        json={"report": "Сделано в тесте", "files": ["main.py"]},
    )
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "done" and done["done_at"]
    assert "Сделано в тесте" in done["report"]

    r = await user_client.get(f"/api/projects/{pid}/worklog")
    entries = r.json()
    assert entries and "Первая задача" in entries[0]["description"]

    job = await latest_job(user_client, pid, "knowledge_update")
    assert job is None, "автозапуск knowledge_update убран — карта обновляется вручную"
    r = await user_client.get(f"/api/projects/{pid}")
    assert r.json()["unsynced_worklogs"] >= 1, "бейдж должен показывать неучтённые работы"

    # ручное «Обновить индекс» подхватывает накопленный worklog одним заходом
    r = await user_client.post(f"/api/projects/{pid}/index", json={"mode": "update"})
    assert r.status_code == 200, r.text
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["stats"]["worklog_synced"] >= 1
    r = await user_client.get(f"/api/projects/{pid}")
    assert r.json()["unsynced_worklogs"] == 0

    # задача есть в графе
    r = await user_client.post(
        f"/api/projects/{pid}/graph/cypher",
        json={"query": "MATCH (t:Task {project_id: $pid}) RETURN t.title AS title, t.status AS status"},
    )
    rows = r.json()
    assert any(row["title"] == "Первая задача" and row["status"] == "done" for row in rows)


def test_rlm_depth_limits() -> None:
    """Глубина: 1 — без углубления, 2 — один вложенный уровень, 0 — до жёсткого потолка."""
    from app.services.rlm import HARD_DEPTH_CAP, _depth_allowed, _parse_followups

    assert _depth_allowed(0, 1) is False
    assert _depth_allowed(0, 2) is True
    assert _depth_allowed(1, 2) is False
    assert _depth_allowed(0, 0) is True
    assert _depth_allowed(HARD_DEPTH_CAP - 1, 0) is False

    # «- да» отсекается как мусор: слишком коротко для осмысленного вопроса
    text = "Ответ по файлам.\n\nНУЖНО УТОЧНИТЬ:\n- где формируется ответ\n- да\n- второй вопрос"
    assert _parse_followups(text, 2) == ["где формируется ответ", "второй вопрос"]
    assert _parse_followups("Ответ без блока", 2) == []
    assert _parse_followups(text, 0) == []


async def test_rlm_recursion_spawns_nested_research(project: dict, monkeypatch) -> None:
    """При глубине 2 ветка, попросившая уточнение, порождает своё исследование."""
    import uuid as _uuid

    from app import config as app_config
    from app.db import get_sessionmaker
    from app.models import Project as ProjectModel
    from app.services import rlm

    monkeypatch.setenv("FAKE_CLAUDE_DEEP", "1")
    monkeypatch.setenv("RLM_MAX_DEPTH", "2")
    app_config.get_settings.cache_clear()

    calls: list[int] = []
    original_sub_query = rlm.sub_query

    async def spy_sub_query(*args, **kwargs):
        calls.append(int(kwargs.get("followup_limit", 0)))
        return await original_sub_query(*args, **kwargs)

    monkeypatch.setattr(rlm, "sub_query", spy_sub_query)
    try:
        async with get_sessionmaker()() as session:
            proj = await session.get(ProjectModel, _uuid.UUID(project["id"]))
        await rlm.answer(proj, "как устроен main.py?")
    finally:
        app_config.get_settings.cache_clear()

    # верхний уровень спрашивал с разрешением углубиться, вложенный — уже без него
    assert len(calls) >= 2, calls
    assert calls[0] > 0, calls
    assert calls[-1] == 0, calls


async def test_rlm_survives_failed_synthesis(project: dict, monkeypatch) -> None:
    """Упавшая финальная сводка не должна съедать работу под-агентов.

    Под-агенты уже прочитали файлы — это самая дорогая часть RLM. Раньше любая
    ошибка синтеза (например, упёршийся в потолок ходов вызов) роняла весь
    пайплайн и исследование терялось целиком.
    """
    import uuid as _uuid

    from app.db import get_sessionmaker
    from app.models import Project as ProjectModel
    from app.services import rlm

    monkeypatch.setenv("FAKE_CLAUDE_FAIL_SYNTH", "1")
    async with get_sessionmaker()() as session:
        proj = await session.get(ProjectModel, _uuid.UUID(project["id"]))

    res = await rlm.answer(proj, "как устроен main.py?")

    assert res["sub_queries"], res
    # вместо исключения вернулись выводы под-агентов, а не пустота
    assert "Группа:" in res["answer"], res["answer"][:300]


async def test_enrich_all_new_takes_only_unenriched(
    user_client: httpx.AsyncClient, project: dict
) -> None:
    """Кнопка «Проработать новые (RLM)»: берёт открытые задачи без проработки и
    не трогает ни уже проработанные, ни закрытые — иначе каждое нажатие гоняло бы
    RLM по всей доске заново."""
    pid = project["id"]

    async def add(title: str) -> dict:
        r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": title})
        assert r.status_code == 201, r.text
        return r.json()

    fresh = await add("Свежая задача")
    already = await add("Уже проработанная")
    closed = await add("Давно закрытая")

    # одну прорабатываем точечно, другую закрываем
    r = await user_client.post(f"/api/projects/{pid}/tasks/{already['id']}/enrich")
    await wait_job(user_client, pid, r.json()["job_id"])
    r = await user_client.post(
        f"/api/projects/{pid}/tasks/{closed['id']}/done", json={"report": "сделано", "files": []}
    )
    assert r.status_code == 200, r.text

    # «Проработать новые» — без task_ids
    r = await user_client.post(f"/api/projects/{pid}/tasks/enrich", json={})
    assert r.status_code == 200, r.text
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["total"] == 1, job["stats"]
    assert job["stats"]["enriched"] == 1, job["stats"]

    tasks = {t["id"]: t for t in (await user_client.get(f"/api/projects/{pid}/tasks")).json()}
    assert tasks[fresh["id"]]["extra"]["enriched"] is True
    assert tasks[closed["id"]]["extra"] == {}, "закрытая задача не должна попадать в проработку"

    # повторное нажатие: брать нечего, и UI об этом узнаёт сразу, а не обещает работу
    r = await user_client.post(f"/api/projects/{pid}/tasks/enrich", json={})
    assert r.status_code == 200, r.text
    assert r.json() == {"job_id": None, "tasks": 0}


async def test_enrich_task_rlm(
    user_client: httpx.AsyncClient, project: dict, monkeypatch
) -> None:
    pid = project["id"]
    r = await user_client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Починить кнопку", "description": "коротко с созвона"},
    )
    task = r.json()
    assert task["extra"] == {}

    # проработка идёт минутами, поэтому следим, что прогресс сообщается по ходу дела,
    # а не единственным разом в самом конце
    from app.jobs_runner import runner

    seen: list[tuple[float, str]] = []
    original_report = runner.report

    async def spy_report(job_id, progress, detail="", stats=None):
        seen.append((progress, detail))
        await original_report(job_id, progress, detail, stats)

    monkeypatch.setattr(runner, "report", spy_report)

    r = await user_client.post(f"/api/projects/{pid}/tasks/{task['id']}/enrich")
    assert r.status_code == 200
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["enriched"] == 1

    values = [p for p, _ in seen]
    assert len(values) >= 3, seen
    assert values == sorted(values), seen
    # есть промежуточные отметки, а не только «начали» и «всё»
    assert any(0.01 < p < 0.9 for p in values), seen
    assert any("исследование" in d for _, d in seen), seen

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    enriched = next(t for t in r.json() if t["id"] == task["id"])
    assert "Детальная проработка" in enriched["description"]
    extra = enriched["extra"]
    assert extra["enriched"] is True
    assert extra["original_description"] == "коротко с созвона"
    assert extra["related"][0]["relation"] == "overlaps"
    # досье: где смотреть / гипотеза / образец / как проверить
    assert extra["where_to_look"][0] == {
        "path": "main.py",
        "why": "объявление обработчика: подключён ли он",
    }
    assert extra["hypothesis"] == {"text": "обработчик не подключён", "confidence": "high"}
    assert "util.py" in extra["reference"]
    assert extra["how_to_verify"][0]["how"].startswith("тестов рядом нет")
    assert extra["reading"]
    # синтез files не отдал — пути берутся из where_to_look
    assert extra["files"] == ["main.py", "src/util.py"]
    # досье не предписывает решение: план остаётся пустым, проработка его не пишет
    assert enriched["plan"] == []


async def test_enrich_retries_broken_json_synthesis(
    user_client: httpx.AsyncClient, project: dict, monkeypatch, tmp_path: Path
) -> None:
    """Синтез иногда отдаёт синтаксически битый JSON. Исследование перед ним идёт
    минуты, а повтор синтеза стоит секунды — одна кривая запятая не должна
    выбрасывать всю проработку."""
    flag = tmp_path / "bad_json_once"
    monkeypatch.setenv("FAKE_CLAUDE_BAD_JSON_ONCE_FILE", str(flag))
    pid = project["id"]
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Задача с ретраем"})
    task_id = r.json()["id"]
    r = await user_client.post(f"/api/projects/{pid}/tasks/{task_id}/enrich")
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"] == {"enriched": 1, "errors": 0, "total": 1}, job["stats"]
    assert flag.exists(), "фейк обязан был отдать битый ответ первым заходом"
    r = await user_client.get(f"/api/projects/{pid}/tasks")
    enriched = next(t for t in r.json() if t["id"] == task_id)
    assert enriched["extra"]["enriched"] is True


async def test_enrich_failure_is_visible_on_finished_job(
    user_client: httpx.AsyncClient, project: dict, monkeypatch
) -> None:
    """Раньше упавшая проработка выглядела зелёной: status=done, progress=100%,
    detail затирался на финише. Пользователь видел «готово» и пустую карточку."""
    monkeypatch.setenv("FAKE_CLAUDE_BAD_JSON", "1")
    pid = project["id"]
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Обречённая задача"})
    task_id = r.json()["id"]
    r = await user_client.post(f"/api/projects/{pid}/tasks/{task_id}/enrich")
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["stats"]["errors"] == 1, job["stats"]
    assert "ошибк" in job["detail"], f"итоговая строка обязана говорить об ошибке: {job['detail']!r}"


async def test_verify_tasks(user_client: httpx.AsyncClient, project: dict) -> None:
    pid = project["id"]
    # фейковый claude отвечает yes только для "Сделать фичу А"
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Сделать фичу А"})
    ta = r.json()
    r = await user_client.post(f"/api/projects/{pid}/tasks", json={"title": "Нереализованная фича"})
    tb = r.json()

    r = await user_client.post(f"/api/projects/{pid}/tasks/verify")
    assert r.status_code == 200
    job = await wait_job(user_client, pid, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["stats"]["done"] >= 1

    r = await user_client.get(f"/api/projects/{pid}/tasks")
    by_id = {t["id"]: t for t in r.json()}
    assert by_id[ta["id"]]["status"] == "done"
    assert "[ИИ-проверка]" in by_id[ta["id"]]["report"]
    assert by_id[tb["id"]]["status"] == "planned"
