"""Schedule the store refresh that recovers a working copy after a write met a newer GitHub revision."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.core.workflow_store.github_io_runtime import shared_github_io_loop

_CONFLICT_REFRESH_FAILED = "github_store_conflict_refresh_failed"
_LIVENESS_POLL_S = 1.0
logger = get_logger(__name__)


class _Run:
    """One chain of conflict refreshes: the running one plus the follow-up that conflicts arriving meanwhile ask for.

    Every field except ``loop`` is guarded by the owning scheduler's lock.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.follow_up = False
        self.task: asyncio.Task[None] | None = None
        self.done: concurrent.futures.Future[None] = concurrent.futures.Future()


class ConflictRefreshScheduler:
    """Hand the store's refresh to a loop when a write's transaction ended on a conflict.

    The refresh never runs inside the failed transaction: its connection is already back in the pool, and the
    refresh takes the working-copy writer itself. One scheduler belongs to one store, and at most one chain of
    refreshes runs per scheduler whichever loop carries it: a conflict that arrives while one runs joins it and
    asks for one follow-up. Where a loop is running, the caller does not wait. A native-sync caller in a process
    with no running loop waits for the chain on the adapter-owned GitHub I/O loop, because nothing else in that
    process would run it before the process ends.
    """

    def __init__(self) -> None:
        self._refresh: Callable[[], Awaitable[object]] | None = None
        self._store_loop: asyncio.AbstractEventLoop | None = None
        self._active: _Run | None = None
        self._stopped = False
        self._lock = threading.Lock()

    def attach(self, refresh: Callable[[], Awaitable[object]]) -> None:
        """Attach the store's refresh operation."""
        self._refresh = refresh

    def serve_store_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that serves this store's async sessions in this process."""
        with self._lock:
            self._store_loop = loop

    def request(self) -> None:
        """Run the refresh for a write that ended on a conflict, joining the chain already running."""
        running = _running_loop()
        store_loop = self._store_loop
        serving = running or (store_loop if store_loop is not None and store_loop.is_running() else None)
        with self._lock:
            if self._stopped:
                return
            run = self._live_run()
            starting = run is None
            if run is None:
                run = _Run(serving or shared_github_io_loop().loop)
                self._active = run
            else:
                run.follow_up = True
        if starting:
            self._start(run)
        if serving is None:
            self._wait(run)

    async def stop(self) -> None:
        """Cancel the running chain, wait until it has ended, and schedule nothing further.

        Terminal: the store this scheduler served is closing, and a write still in flight may yet end on a conflict.
        """
        with self._lock:
            self._stopped = True
            run = self._active
            if run is None:
                return
            task = run.task
            if task is None or not run.loop.is_running():
                self._release(run)
                return
        try:
            run.loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            with self._lock:
                self._release(run)
            return
        await asyncio.wrap_future(run.done)

    def _live_run(self) -> _Run | None:
        """Return the active chain, dropping one whose loop is gone and so can never end it. Lock held."""
        run = self._active
        if run is not None and not run.loop.is_running():
            self._release(run)
            return None
        return run

    def _release(self, run: _Run) -> None:
        """End a chain's bookkeeping. Lock held; safe to repeat."""
        if self._active is run:
            self._active = None
        if not run.done.done():
            run.done.set_result(None)

    def _start(self, run: _Run) -> None:
        coroutine = self._run(run)
        try:
            asyncio.run_coroutine_threadsafe(coroutine, run.loop)
        except RuntimeError as error:
            coroutine.close()
            logger.warning(_CONFLICT_REFRESH_FAILED, reason=type(error).__name__, exc_info=True)
            with self._lock:
                self._release(run)

    def _wait(self, run: _Run) -> None:
        while True:
            try:
                run.done.result(timeout=_LIVENESS_POLL_S)
                return
            except concurrent.futures.TimeoutError:
                if not run.loop.is_running():
                    return

    async def _run(self, run: _Run) -> None:
        with self._lock:
            if run.done.done():
                return
            run.task = asyncio.current_task()
        try:
            while True:
                with self._lock:
                    run.follow_up = False
                try:
                    await self._run_refresh()
                except Exception as error:
                    logger.warning(_CONFLICT_REFRESH_FAILED, reason=type(error).__name__, exc_info=True)
                with self._lock:
                    if not run.follow_up:
                        self._release(run)
                        return
        finally:
            with self._lock:
                self._release(run)

    async def _run_refresh(self) -> None:
        if self._refresh is not None:
            await self._refresh()


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
