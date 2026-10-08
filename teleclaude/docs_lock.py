"""Bounded cooperative access to deployed documentation generations."""

from __future__ import annotations

import errno
import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.paths import DOCS_DEPLOYMENT_LOCK_PATH

logger = get_logger(__name__)

# A publication holds the lease for its whole build, which routinely runs longer
# than a minute; a waiter outlasts several such holds before it gives up.
DOCS_LOCK_TIMEOUT_SECONDS = 600.0
_RETRY_INTERVAL_SECONDS = 0.1
_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN})
_HOLDER_RECORD = "pid {pid} ({operation})"
_HOLDER_UNKNOWN = "an unrecorded holder"
_HOLDER_READ_BYTES = 256
_TIMEOUT_MESSAGE = "documentation {operation} lease timed out after {waited:.1f}s; held by {holder}"
_UTF8 = "utf-8"
_UNDECODABLE = "replace"


class DocsLockOperation(StrEnum):
    """The pipeline operation represented by one lease record."""

    SYNCHRONIZATION = "synchronization"


class DocsLeaseTimeoutError(TimeoutError):
    """A documentation operation could not obtain its bounded lease."""


@contextmanager
def docs_lease(
    operation: DocsLockOperation,
    *,
    timeout_seconds: float = DOCS_LOCK_TIMEOUT_SECONDS,
) -> Generator[int, None, None]:
    """Yield an exclusively held documentation-lock descriptor for one bounded deploy.

    Validation reads publisher sources and takes no lease; only a deploy that
    replaces the published tree holds this lock.
    """
    DOCS_DEPLOYMENT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(DOCS_DEPLOYMENT_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    requested_at = time.monotonic()
    logger.info("docs_lease_requested", operation=operation)
    holder: str | None = None
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in _CONTENTION_ERRNOS:
                    raise
                if holder is None:
                    holder = _read_holder(descriptor)
                    logger.info("docs_lease_waiting", operation=operation, holder=holder)
                waited_seconds = time.monotonic() - requested_at
                if waited_seconds >= timeout_seconds:
                    holder = _read_holder(descriptor)
                    logger.warning(
                        "docs_lease_timeout",
                        operation=operation,
                        waited_seconds=waited_seconds,
                        holder=holder,
                    )
                    raise DocsLeaseTimeoutError(
                        _TIMEOUT_MESSAGE.format(operation=operation, waited=waited_seconds, holder=holder)
                    ) from exc
                time.sleep(min(_RETRY_INTERVAL_SECONDS, timeout_seconds - waited_seconds))
        _record_holder(descriptor, operation)
        logger.info(
            "docs_lease_acquired",
            operation=operation,
            waited_seconds=time.monotonic() - requested_at,
        )
        yield descriptor
    finally:
        os.close(descriptor)
        logger.info("docs_lease_released", operation=operation)


def _record_holder(descriptor: int, operation: DocsLockOperation) -> None:
    """Write the holding process into the lock file so a waiter can name it."""
    os.ftruncate(descriptor, 0)
    os.pwrite(descriptor, _HOLDER_RECORD.format(pid=os.getpid(), operation=operation).encode(_UTF8), 0)


def _read_holder(descriptor: int) -> str:
    """The holder the current lease recorded, read without taking the lock."""
    recorded = os.pread(descriptor, _HOLDER_READ_BYTES, 0).decode(_UTF8, errors=_UNDECODABLE).strip()
    return recorded or _HOLDER_UNKNOWN
