"""Filesystem watcher for todos/ directories across trusted projects.

Watches for changes to roadmap.md, state.json, and directory structure within
todos/ and triggers granular cache updates via the daemon cache.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from instrukt_ai_logging import get_logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from teleclaude.config import config
from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

# Temp file suffixes to ignore
_IGNORED_SUFFIXES = {".swp", ".tmp", ".bak", "~"}

# Debounce window per project (seconds)
_DEBOUNCE_S = 1.0


def _is_relevant(path: str) -> bool:
    """Check if a filesystem event path is relevant for todo tracking."""
    p = Path(path)
    name = p.name

    # Ignore hidden paths inside todo trees.
    if any(part.startswith(".") for part in p.parts):
        return False

    # Ignore temp/editor files
    if any(name.endswith(suf) for suf in _IGNORED_SUFFIXES):
        return False

    # Directory events under todos/ are relevant (slug dir created/deleted)
    if p.is_dir() or not p.suffix:
        return True

    # Any non-hidden file under todos/ can affect preparation metadata.
    return True


def _classify_event(event: FileSystemEvent) -> str:
    """Map watchdog event type to cache event hint."""
    event_type = event.event_type
    if event_type == "created":
        return "todo_created"
    if event_type == "deleted":
        return "todo_removed"
    return "todo_updated"


class _TodoHandler(FileSystemEventHandler):
    """Watchdog handler that queues todo refresh requests."""

    def __init__(
        self, project_path: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[tuple[str, str]]
    ) -> None:
        super().__init__()
        self._project_path = project_path
        self._loop = loop
        self._queue = queue

    def _handle(self, event: FileSystemEvent) -> None:
        src = event.src_path
        if not isinstance(src, str) or not _is_relevant(src):
            return
        hint = _classify_event(event)
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (self._project_path, hint))
        except RuntimeError:
            pass  # Loop closed

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._handle(event)


class TodoWatcher:
    """Watches todos/ directories for all trusted projects and updates the cache."""

    def __init__(self, cache: DaemonCache) -> None:
        self._cache = cache
        self._observer: object | None = None

    async def run(self) -> None:
        """Start watching and process events until cancelled."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        computer_name = config.computer.name

        observer = Observer()
        observer.daemon = True
        self._observer = observer

        watched = 0
        for td in config.computer.get_all_trusted_dirs():
            todos_dir = Path(td.path) / "todos"
            if not todos_dir.is_dir():
                continue
            handler = _TodoHandler(td.path, loop, queue)
            observer.schedule(handler, str(todos_dir), recursive=True)
            watched += 1
            logger.debug("TodoWatcher: watching %s", todos_dir)

        if watched == 0:
            logger.info("TodoWatcher: no todos/ directories found, watcher idle")
            # Stay alive but do nothing — new projects would need a restart
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

        observer.start()
        logger.info("TodoWatcher: started, watching %d project(s)", watched)

        # Debounce state: project_path -> (last_event_time, last_hint)
        pending: dict[str, tuple[float, str]] = {}

        try:
            while True:
                # Drain queue with short timeout to process debounced items
                try:
                    project_path, hint = await asyncio.wait_for(queue.get(), timeout=0.5)
                    pending[project_path] = (time.monotonic(), hint)
                except asyncio.TimeoutError:
                    pass

                # Process items past the debounce window
                now = time.monotonic()
                ready = [pp for pp, (ts, _) in pending.items() if now - ts >= _DEBOUNCE_S]
                for pp in ready:
                    _, hint = pending.pop(pp)
                    try:
                        await self._cache.refresh_local_todos(computer_name, pp, hint)
                        logger.debug("TodoWatcher: refreshed %s (event=%s)", pp, hint)
                    except Exception as exc:
                        logger.warning("TodoWatcher: refresh failed for %s: %s", pp, exc)

        except asyncio.CancelledError:
            pass
        finally:
            observer.stop()
            observer.join(timeout=2)
            logger.info("TodoWatcher: stopped")
