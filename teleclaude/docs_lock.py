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

DOCS_LOCK_TIMEOUT_SECONDS = 30.0
_RETRY_INTERVAL_SECONDS = 0.1
_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN})


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
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in _CONTENTION_ERRNOS:
                    raise
                waited_seconds = time.monotonic() - requested_at
                if waited_seconds >= timeout_seconds:
                    logger.warning(
                        "docs_lease_timeout",
                        operation=operation,
                        waited_seconds=waited_seconds,
                    )
                    raise DocsLeaseTimeoutError(
                        f"documentation {operation} lease timed out after {waited_seconds:.1f}s"
                    ) from exc
                time.sleep(min(_RETRY_INTERVAL_SECONDS, timeout_seconds - waited_seconds))
        logger.info(
            "docs_lease_acquired",
            operation=operation,
            waited_seconds=time.monotonic() - requested_at,
        )
        yield descriptor
    finally:
        os.close(descriptor)
        logger.info("docs_lease_released", operation=operation)
