from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select, update

from .config import get_settings
from .db import get_sessionmaker
from .models import Job, utcnow

log = logging.getLogger("projectai.jobs")

# handler(job_id, project_id, params) -> stats dict
JobHandler = Callable[[uuid.UUID, uuid.UUID, dict], Awaitable[dict]]


class JobCancelled(Exception):
    """Задача отменена пользователем — хендлер прерывает работу."""


class JobRunner:
    """Встроенный асинхронный исполнитель фоновых задач с персистентностью в Postgres.

    Для self-hosted установки отдельный воркер-процесс не нужен: тяжёлые CPU-задачи
    уходят в поток через asyncio.to_thread, ИИ-задачи — subprocess claude -p.
    """

    def __init__(self, concurrency: int = 3) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._concurrency = concurrency
        self._running = False
        # SSE-подписчики: project_id -> очереди событий
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}
        # запрошенные отмены выполняющихся задач
        self._cancel_requested: set[uuid.UUID] = set()

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    # --- события (SSE) ---

    def subscribe(self, project_id: uuid.UUID) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.setdefault(project_id, set()).add(q)
        return q

    def unsubscribe(self, project_id: uuid.UUID, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(project_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(project_id, None)

    def publish(self, project_id: uuid.UUID, event: dict) -> None:
        for q in self._subscribers.get(project_id, ()):  # медленный подписчик теряет события
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def _publish_job(self, job_id: uuid.UUID) -> None:
        from .schemas import JobOut

        async with get_sessionmaker()() as session:
            job = await session.get(Job, job_id)
        if job is not None:
            self.publish(
                job.project_id,
                {"type": "job", "job": JobOut.model_validate(job).model_dump(mode="json")},
            )

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # задачи, зависшие после рестарта, помечаем ошибкой
        async with get_sessionmaker()() as session:
            await session.execute(
                update(Job)
                .where(Job.status.in_(["queued", "running"]))
                .values(status="error", error="Прервано перезапуском сервера", finished_at=utcnow())
            )
            await session.commit()
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self._concurrency)]
        log.info("JobRunner: %d воркеров запущено", self._concurrency)

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers = []

    async def submit(self, project_id: uuid.UUID, job_type: str, params: dict | None = None) -> Job:
        if job_type not in self._handlers:
            raise ValueError(f"Неизвестный тип задачи: {job_type}")
        async with get_sessionmaker()() as session:
            job = Job(project_id=project_id, type=job_type, params=params or {})
            session.add(job)
            await session.commit()
            await session.refresh(job)
        await self._queue.put(job.id)
        await self._publish_job(job.id)
        return job

    async def cancel(self, job_id: uuid.UUID) -> str | None:
        """Отмена: queued помечается сразу, running получает флаг —
        хендлер проверяет его между батчами через check_cancelled()."""
        async with get_sessionmaker()() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return None
            if job.status == "queued":
                job.status = "cancelled"
                job.detail = "Отменено пользователем"
                job.finished_at = utcnow()
                await session.commit()
                await self._publish_job(job_id)
                return "cancelled"
            if job.status == "running":
                self._cancel_requested.add(job_id)
                await session.execute(
                    update(Job).where(Job.id == job_id).values(detail="Отменяется…")
                )
                await session.commit()
                await self._publish_job(job_id)
                return "cancelling"
        return None

    def is_cancelled(self, job_id: uuid.UUID) -> bool:
        return job_id in self._cancel_requested

    def check_cancelled(self, job_id: uuid.UUID) -> None:
        if job_id in self._cancel_requested:
            raise JobCancelled()

    async def has_active(self, project_id: uuid.UUID, types: list[str] | None = None) -> bool:
        async with get_sessionmaker()() as session:
            q = select(Job.id).where(
                Job.project_id == project_id, Job.status.in_(["queued", "running"])
            )
            if types:
                q = q.where(Job.type.in_(types))
            res = await session.execute(q.limit(1))
            return res.first() is not None

    async def _worker(self, n: int) -> None:
        while self._running:
            try:
                job_id = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("Воркер %d: необработанная ошибка задачи %s", n, job_id)

    async def _run_job(self, job_id: uuid.UUID) -> None:
        maker = get_sessionmaker()
        async with maker() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            job.started_at = utcnow()
            await session.commit()
            job_type, project_id, params = job.type, job.project_id, dict(job.params)
        await self._publish_job(job_id)

        handler = self._handlers[job_type]
        try:
            stats = await handler(job_id, project_id, params)
            async with maker() as session:
                await session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(status="done", progress=1.0, stats=stats or {}, finished_at=utcnow(), detail="")
                )
                await session.commit()
        except JobCancelled:
            log.info("Задача %s (%s) отменена пользователем", job_id, job_type)
            async with maker() as session:
                await session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(status="cancelled", detail="Отменено пользователем", finished_at=utcnow())
                )
                await session.commit()
        except Exception as e:
            log.exception("Задача %s (%s) упала", job_id, job_type)
            async with maker() as session:
                await session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status="error",
                        error=f"{e}\n{traceback.format_exc(limit=5)}",
                        finished_at=utcnow(),
                    )
                )
                await session.commit()
        finally:
            self._cancel_requested.discard(job_id)
        await self._publish_job(job_id)

    async def report(self, job_id: uuid.UUID, progress: float, detail: str = "", stats: dict | None = None) -> None:
        """Вызывается из хендлеров для обновления прогресса."""
        values: dict[str, Any] = {"progress": max(0.0, min(1.0, progress))}
        if detail:
            values["detail"] = detail[:300]
        if stats is not None:
            values["stats"] = stats
        async with get_sessionmaker()() as session:
            await session.execute(update(Job).where(Job.id == job_id).values(**values))
            await session.commit()
        await self._publish_job(job_id)


runner = JobRunner(get_settings().job_concurrency)
