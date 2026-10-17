"""Carry the admitted payload's original work cutoff through existing synchronous command paths."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

NANOSECONDS: Final = 1_000_000_000
EXPIRED: Final = "The original admitted payload work allowance is exhausted."
_END: ContextVar[int | None] = ContextVar("acceptance_work_end_ns", default=None)


@contextmanager
def scope(end_ns: int | None) -> Iterator[None]:
    """Bind only this invocation; nesting cannot extend an already admitted cutoff."""
    previous = _END.get()
    if previous is not None:
        end_ns = previous if end_ns is None else min(previous, end_ns)
    token = _END.set(end_ns)
    try:
        yield
    finally:
        _END.reset(token)


def expired() -> bool:
    """Read the original cutoff without changing or refreshing it."""
    end_ns = _END.get()
    return end_ns is not None and time.monotonic_ns() >= end_ns


def check() -> None:
    """Refuse further public work once the admitted payload allowance expires."""
    if expired():
        raise TimeoutError(EXPIRED)


def command_end(seconds: float) -> int:
    """Intersect a caller's existing command cap with the same original work end."""
    check()
    end_ns = time.monotonic_ns() + int(seconds * NANOSECONDS)
    work_end = _END.get()
    return end_ns if work_end is None else min(end_ns, work_end)


def remaining(end_ns: int) -> float:
    """Return zero at expiry, suitable for existing native timeout APIs."""
    return max(0.0, (end_ns - time.monotonic_ns()) / NANOSECONDS)


def sleep(seconds: float) -> None:
    """Keep an existing journey pause within the admitted work allowance."""
    end_ns = command_end(seconds)
    time.sleep(remaining(end_ns))
    check()
