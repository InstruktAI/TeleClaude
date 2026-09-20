"""Transient per-session ownership for terminal runtime mutations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class RuntimeMutationInProgress(RuntimeError):
    """Raised when a competing runtime mutation targets an owned session."""


_runtime_locks: dict[str, asyncio.Lock] = {}


class SessionRuntimeLease:
    """An acquired runtime owner that can span asynchronous handoff admission."""

    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        self.release()

    def release(self) -> None:
        if self._lock.locked():
            self._lock.release()


def runtime_mutation_active(session_id: str) -> bool:
    """Return whether a session currently has a runtime mutation owner."""
    lock = _runtime_locks.get(session_id)
    return lock.locked() if lock is not None else False


@asynccontextmanager
async def session_runtime_owner(session_id: str, *, wait: bool = False) -> AsyncIterator[None]:
    """Acquire exclusive runtime ownership, waiting only for durable inbound delivery."""
    lease = await acquire_session_runtime_lease(session_id, wait=wait)
    try:
        yield
    finally:
        lease.release()


async def acquire_session_runtime_lease(session_id: str, *, wait: bool = False) -> SessionRuntimeLease:
    """Acquire a lease that a handoff can retain from admission through completion."""
    lock = _runtime_locks.setdefault(session_id, asyncio.Lock())
    if lock.locked() and not wait:
        raise RuntimeMutationInProgress("runtime_mutation_in_progress")
    await lock.acquire()
    return SessionRuntimeLease(lock)
