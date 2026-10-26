"""Own shared request serialization and pacing state for GitHub workflow I/O."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from time import monotonic
from typing import Any

_THREAD_NAME = "teleclaude-github-io"
_PACED_WRITE_INTERVAL_S = 1.0
_INTER_ITEM_WRITE_INTERVAL_S = 10.0


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
    """Own the single process loop used by every project's sync and async caller.

    `request_lock` keeps GitHub requests one at a time, held for a single request. `unit_lock` keeps
    background units (a reflection, a pull request unit) from interleaving; only background units hold it,
    never a push that owns the working copy's writer, so a push waits behind at most one request.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.request_lock: asyncio.Lock | None = None
        self.unit_lock: asyncio.Lock | None = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name=_THREAD_NAME, daemon=True)
        self.thread.start()
        self.ready.wait()

    def submit(self, coroutine: Any) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.request_lock = asyncio.Lock()
        self.unit_lock = asyncio.Lock()
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
