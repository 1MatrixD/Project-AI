from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .jobs_runner import runner
from .routers import auth, chats, decisions, files, fs, jobs, materials, projects, tasks
from .services import git_import, graphdb, indexer, planner, task_enrich, vectors
from .services.materials import process_material
from .services.plugin_gen import plugin_generate_job
from .services.watcher import watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("projectai")


async def _ensure_graph_ready(retries: int = 30) -> None:
    for attempt in range(retries):
        try:
            await graphdb.ensure_constraints()
            return
        except Exception as e:
            if attempt == retries - 1:
                log.error("Neo4j недоступен: %s", e)
                return
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _ensure_graph_ready()

    runner.register("index", indexer.index_project)
    runner.register("knowledge_update", indexer.knowledge_update)
    runner.register("verify_tasks", indexer.verify_tasks)
    runner.register("enrich_tasks", task_enrich.enrich_tasks)
    runner.register("plan_task", planner.plan_task)
    runner.register("git_import", git_import.git_import)
    runner.register("process_material", process_material)
    runner.register("plugin_generate", plugin_generate_job)
    await runner.start()
    await watcher.resume_all()

    log.info("Проекты ИИ: API готов на порту %d", get_settings().api_port)
    yield

    watcher.shutdown()
    await runner.stop()
    await graphdb.close_driver()
    await vectors.close_client()


app = FastAPI(title="Проекты ИИ", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, fs.router, projects.router, files.router, jobs.router, chats.router, tasks.router, materials.router, decisions.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "Проекты ИИ"}
