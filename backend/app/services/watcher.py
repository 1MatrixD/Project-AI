from __future__ import annotations

import asyncio
import logging
import os
import uuid

from sqlalchemy import select
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ..config import get_settings
from ..db import get_sessionmaker
from ..jobs_runner import runner
from ..models import Project
from .scanner import IGNORED_DIRS, IGNORED_EXTENSIONS, IGNORED_FILES

log = logging.getLogger("projectai.watcher")

"""Наблюдение за каталогом проекта (watchdog): изменения в коде с дебаунсом
автоматически запускают инкрементальное обновление индекса.

Включается per-проект (project.meta.watch), переживает рестарт сервера
(resume_all при старте). События из служебных каталогов (.git, node_modules и
т.п.) отфильтровываются до дебаунса; шумовые срабатывания без реальных изменений
гасятся уже в индексаторе (trigger=watch + пустой diff → без ИИ-анализа).
"""


def _is_noise(path: str) -> bool:
    """Событие из служебного каталога/файла — не повод переиндексировать."""
    parts = path.replace("\\", "/").split("/")
    if any(p.lower() in IGNORED_DIRS or p.startswith(".git") for p in parts):
        return True
    name = parts[-1]
    if name in IGNORED_FILES:
        return True
    return os.path.splitext(name)[1].lower() in IGNORED_EXTENSIONS


class _Handler(FileSystemEventHandler):
    def __init__(self, manager: WatcherManager, project_id: uuid.UUID) -> None:
        self._manager = manager
        self._project_id = project_id

    def on_any_event(self, event: FileSystemEvent) -> None:  # поток наблюдателя
        if event.is_directory and event.event_type == "modified":
            return  # дублируется событием самого файла
        path = str(getattr(event, "dest_path", "") or event.src_path)
        if _is_noise(path):
            return
        self._manager.notify_change(self._project_id)


class WatcherManager:
    """Один Observer-поток на процесс, watch на каждый корень включённого
    проекта (мультирепо — несколько каталогов)."""

    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._watches: dict[uuid.UUID, list[object]] = {}
        self._pending: dict[uuid.UUID, asyncio.Task] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def is_watching(self, project_id: uuid.UUID) -> bool:
        return project_id in self._watches

    def start_watch(self, project_id: uuid.UUID, root_paths: str | list[str]) -> None:
        if project_id in self._watches:
            return
        paths = [root_paths] if isinstance(root_paths, str) else list(root_paths)
        for p in paths:
            if not os.path.isdir(p):
                raise FileNotFoundError(f"Каталог не найден: {p}")
        self._loop = asyncio.get_running_loop()
        if self._observer is None:
            self._observer = Observer()
            self._observer.daemon = True
            self._observer.start()
        handler = _Handler(self, project_id)
        self._watches[project_id] = [
            self._observer.schedule(handler, p, recursive=True) for p in paths
        ]
        log.info("Наблюдение включено: %s (%s)", project_id, ", ".join(paths))

    def restart_watch(self, project_id: uuid.UUID, root_paths: list[str]) -> None:
        """Перечитать набор корней (добавили/убрали каталог при включённом watch)."""
        if project_id not in self._watches:
            return
        self.stop_watch(project_id)
        self.start_watch(project_id, root_paths)

    def stop_watch(self, project_id: uuid.UUID) -> None:
        watches = self._watches.pop(project_id, None)
        if watches and self._observer is not None:
            for watch in watches:
                try:
                    self._observer.unschedule(watch)
                except Exception:
                    pass
            log.info("Наблюдение выключено: %s", project_id)
        pending = self._pending.pop(project_id, None)
        if pending is not None:
            pending.cancel()

    def notify_change(self, project_id: uuid.UUID) -> None:
        """Вызывается из потока наблюдателя — перекидываем в event loop."""
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._debounce, project_id)

    def _debounce(self, project_id: uuid.UUID) -> None:
        if project_id not in self._watches or self._loop is None:
            return
        prev = self._pending.pop(project_id, None)
        if prev is not None:
            prev.cancel()
        self._pending[project_id] = self._loop.create_task(self._wait_and_trigger(project_id))

    async def _wait_and_trigger(self, project_id: uuid.UUID) -> None:
        try:
            await asyncio.sleep(get_settings().watch_debounce_sec)
            # индексация уже идёт — ждём и пробуем снова (новые события сбросят таймер)
            while await runner.has_active(project_id, ["index"]):
                await asyncio.sleep(max(2.0, get_settings().watch_debounce_sec))
            if project_id not in self._watches:
                return
            await runner.submit(project_id, "index", {"mode": "update", "trigger": "watch"})
            log.info("Watch: изменения в проекте %s — обновляю индекс", project_id)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Watch-триггер проекта %s упал", project_id)
        finally:
            if self._pending.get(project_id) is asyncio.current_task():
                self._pending.pop(project_id, None)

    async def resume_all(self) -> None:
        """При старте сервера возобновляет наблюдение для проектов с meta.watch."""
        async with get_sessionmaker()() as session:
            res = await session.execute(select(Project))
            projects = list(res.scalars())
        from .roots import get_roots

        for p in projects:
            if (p.meta or {}).get("watch"):
                try:
                    self.start_watch(p.id, [r for _a, r in get_roots(p)])
                except Exception as e:
                    log.warning("Не удалось возобновить наблюдение «%s»: %s", p.name, e)

    def shutdown(self) -> None:
        for pid in list(self._watches):
            self.stop_watch(pid)
        if self._observer is not None:
            self._observer.stop()
            self._observer = None


watcher = WatcherManager()
