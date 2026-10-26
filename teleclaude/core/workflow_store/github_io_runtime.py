"""Own shared request serialization and pacing state for GitHub workflow I/O."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from time import monotonic
from typing import Any

from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused

_THREAD_NAME = "teleclaude-github-io"
_PACED_WRITE_INTERVAL_S = 1.0
_INTER_ITEM_WRITE_INTERVAL_S = 10.0
_LOCK_WAIT_SECONDS = 30.0
_UNIT_SECONDS = 180.0
_LOCK_WAIT_DETAIL = "request lock wait exceeded"


@dataclass
class GitHubMutationPacing:
    """Count mutative requests and pace between committed migration batches."""

    count: int = 0
    last_start: float = 0.0
    last_wait_ended: float = 0.0
    count_at_wait: int = 0

    async def wait_between_items(self) -> None:
        while True:
            current_count = self.count
            required = (current_count - self.count_at_wait) * _INTER_ITEM_WRITE_INTERVAL_S
            elapsed = monotonic() - self.last_wait_ended
            remaining = required - elapsed
            if remaining <= 0:
                break
            await asyncio.sleep(remaining)
        self.count_at_wait = current_count
        self.last_wait_ended = monotonic()


class _GitHubIOLoop:
    """Own the single process loop used by every project's sync and async caller."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.request_lock: asyncio.Lock | None = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name=_THREAD_NAME, daemon=True)
        self.thread.start()
        self.ready.wait()

    def submit(self, coroutine: Any) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.request_lock = asyncio.Lock()
        self.ready.set()
        self.loop.run_forever()


_io_loop: _GitHubIOLoop | None = None
_io_loop_lock = threading.Lock()


def shared_github_io_loop() -> _GitHubIOLoop:
    """Return the process-wide GitHub I/O loop, creating its single worker if needed."""
    global _io_loop
    with _io_loop_lock:
        if _io_loop is None:
            _io_loop = _GitHubIOLoop()
        return _io_loop


async def run_serialized_unit[Result](work: Callable[[], Awaitable[Result]], *, unit_detail: str) -> Result:
    """Run one unit of GitHub requests while holding the process-wide request lock, within bounded waits.

    Every GitHub request the workflow store makes runs inside such a unit, so no two requests are ever in flight
    at once and a stuck unit cannot hold the lock for ever.
    """
    io_loop = shared_github_io_loop()
    if io_loop.request_lock is None:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    try:
        await asyncio.wait_for(io_loop.request_lock.acquire(), _LOCK_WAIT_SECONDS)
    except TimeoutError:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_LOCK_WAIT_DETAIL) from None
    try:
        async with asyncio.timeout(_UNIT_SECONDS):
            return await work()
    except TimeoutError:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=unit_detail) from None
    finally:
        io_loop.request_lock.release()
