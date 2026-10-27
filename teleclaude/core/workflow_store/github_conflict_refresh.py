"""Schedule the store refresh that recovers a working copy after a write met a newer GitHub revision."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.core.workflow_store.github_io_runtime import shared_github_io_loop

_CONFLICT_REFRESH_FAILED = "github_store_conflict_refresh_failed"
logger = get_logger(__name__)


class _LoopRefresh:
    """Run refreshes on one loop: one at a time, plus one follow-up for conflicts that arrive meanwhile."""

    def __init__(self, loop: asyncio.AbstractEventLoop, refresh: Callable[[], Awaitable[object]]) -> None:
        self.loop = loop
        self._refresh = refresh
        self._task: asyncio.Task[None] | None = None
        self._follow_up = False

    def request(self) -> asyncio.Task[None]:
        """Start a refresh, or ask the running one for a follow-up. Runs on this loop's thread."""
        if self._task is None:
            self._task = self.loop.create_task(self._run())
        else:
            self._follow_up = True
        return self._task

    async def stop(self) -> None:
        """Cancel the running refresh and wait until it has ended, from any loop."""
        if _running_loop() is self.loop:
            await self._cancel()
        elif self.loop.is_running():
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(self._cancel(), self.loop))

    async def _cancel(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        try:
            while True:
                self._follow_up = False
                try:
                    await self._refresh()
                except Exception as error:
                    logger.warning(_CONFLICT_REFRESH_FAILED, reason=type(error).__name__, exc_info=True)
                if not self._follow_up:
                    return
        finally:
            self._task = None


class ConflictRefreshScheduler:
    """Hand the store's refresh to a loop when a write's transaction ended on a conflict.

    The refresh never runs inside the failed transaction: its connection is already back in the pool, and the
    refresh takes the working-copy writer itself. Where a loop is running, the caller does not wait for it. A
    native-sync caller in a process with no running store loop waits for the refresh on the adapter-owned
    GitHub I/O loop, because nothing else in that process would run it before the process ends.
    """

    def __init__(self) -> None:
        self._refresh: Callable[[], Awaitable[int]] | None = None
        self._store_loop: asyncio.AbstractEventLoop | None = None
        self._by_loop: dict[asyncio.AbstractEventLoop, _LoopRefresh] = {}
        self._lock = threading.Lock()

    def attach(self, refresh: Callable[[], Awaitable[int]]) -> None:
        """Attach the store's refresh operation."""
        self._refresh = refresh

    def serve_store_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that serves this store's async sessions in this process."""
        with self._lock:
            self._store_loop = loop
            for known in [known for known in self._by_loop if known.is_closed()]:
                del self._by_loop[known]

    def request(self) -> None:
        """Run the refresh once for a write that ended on a conflict, coalescing with one already running."""
        running = _running_loop()
        if running is not None:
            self._schedule(running)
            return
        store_loop = self._store_loop
        if store_loop is not None and store_loop.is_running():
            self._schedule(store_loop)
            return
        self._run_on_io_loop()

    async def stop(self) -> None:
        """Cancel every in-flight refresh and wait until each has ended."""
        with self._lock:
            entries = list(self._by_loop.values())
        for entry in entries:
            await entry.stop()

    def _entry(self, loop: asyncio.AbstractEventLoop) -> _LoopRefresh:
        with self._lock:
            entry = self._by_loop.get(loop)
            if entry is None:
                entry = self._by_loop[loop] = _LoopRefresh(loop, self._run_refresh)
            return entry

    def _schedule(self, loop: asyncio.AbstractEventLoop) -> None:
        entry = self._entry(loop)
        if _running_loop() is loop:
            entry.request()
            return
        try:
            loop.call_soon_threadsafe(entry.request)
        except RuntimeError as error:
            logger.warning(_CONFLICT_REFRESH_FAILED, reason=type(error).__name__, exc_info=True)

    def _run_on_io_loop(self) -> None:
        future = shared_github_io_loop().submit(self._wait_on_io_loop())
        try:
            future.result()
        except Exception as error:
            logger.warning(_CONFLICT_REFRESH_FAILED, reason=type(error).__name__, exc_info=True)

    async def _wait_on_io_loop(self) -> None:
        # Shielded: a waiter that gives up must not cancel the refresh other waiters share.
        await asyncio.shield(self._entry(asyncio.get_running_loop()).request())

    async def _run_refresh(self) -> None:
        if self._refresh is not None:
            await self._refresh()


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
