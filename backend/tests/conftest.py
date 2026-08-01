from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

# --- окружение ДО импорта приложения (Settings кэшируется) ---
BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_file = REPO / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


_env = _load_env()
_pg_password = _env.get("POSTGRES_PASSWORD", "projectai")
TEST_DB_URL = f"postgresql+asyncpg://projectai:{_pg_password}@localhost:5432/projectai_test"

_tmp_data = tempfile.mkdtemp(prefix="projectai-test-data-")

# фейковый claude: .py-скрипт, claude_cli запустит его текущим python
_fake_cmd = BACKEND / "tests" / "fake_claude.py"

os.environ.update(
    {
        "DATABASE_URL": TEST_DB_URL,
        "NEO4J_URI": _env.get("NEO4J_URI", "bolt://localhost:7687"),
        "NEO4J_USER": _env.get("NEO4J_USER", "neo4j"),
        "NEO4J_PASSWORD": _env.get("NEO4J_PASSWORD", ""),
        "JWT_SECRET": "test-secret",
        "DATA_DIR": _tmp_data,
        "CLAUDE_BIN": str(_fake_cmd),
        "AI_ANALYSIS_ENABLED": "true",
        "AI_MAX_FILES_PER_RUN": "10",
        "AI_BATCH_SIZE": "5",
        "AI_CONCURRENCY": "2",
        "CLAUDE_TIMEOUT_SEC": "60",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


async def _recreate_test_db() -> None:
    conn = await asyncpg.connect(
        user="projectai", password=_pg_password, database="projectai", host="localhost", port=5432
    )
    try:
        await conn.execute("DROP DATABASE IF EXISTS projectai_test WITH (FORCE)")
        await conn.execute("CREATE DATABASE projectai_test")
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def client():
    await _recreate_test_db()

    from app.db import init_db
    from app.jobs_runner import runner
    from app.main import app
    from app.services import graphdb, indexer
    from app.services.materials import process_material
    from app.services.plugin_gen import plugin_generate_job

    await init_db()
    try:
        await graphdb.ensure_constraints()
    except Exception:
        pass
    runner.register("index", indexer.index_project)
    runner.register("knowledge_update", indexer.knowledge_update)
    runner.register("verify_tasks", indexer.verify_tasks)
    runner.register("process_material", process_material)
    runner.register("plugin_generate", plugin_generate_job)
    await runner.start()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await runner.stop()
    await graphdb.close_driver()


@pytest_asyncio.fixture
async def user_client(client: httpx.AsyncClient):
    """Клиент с авторизованным пользователем."""
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "name": "Тест"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    client.headers.pop("Authorization", None)


@pytest.fixture
def sample_project_dir(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "main.py").write_text("def main():\n    print('hi')\n", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Тестовый проект\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    return tmp_path


async def wait_job(client: httpx.AsyncClient, project_id: str, job_id: str, timeout: float = 60.0) -> dict:
    """Ждёт завершения фоновой задачи."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        r = await client.get(f"/api/projects/{project_id}/jobs/{job_id}")
        assert r.status_code == 200, r.text
        job = r.json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"Задача не завершилась: {job}")
        await asyncio.sleep(0.3)


async def latest_job(client: httpx.AsyncClient, project_id: str, job_type: str) -> dict | None:
    r = await client.get(f"/api/projects/{project_id}/jobs")
    for j in r.json():
        if j["type"] == job_type:
            return j
    return None

