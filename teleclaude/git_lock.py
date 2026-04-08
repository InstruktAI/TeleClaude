"""Process-level flock for main-branch git mutations.

Serializes concurrent bookkeeping commits and integration pushes
to prevent push races and index.lock conflicts on origin/main.
"""

from __future__ import annotations

import fcntl
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.paths import GIT_MAIN_LOCK_PATH

logger = get_logger(__name__)

_LOCK_PATH = GIT_MAIN_LOCK_PATH


@contextmanager
def main_branch_lock() -> Generator[None, None, None]:
    """Acquire an exclusive flock on the main-branch lock file.

    Blocks until the lock is acquired. The lock is released when the
    context manager exits (fd closed → flock released).
    """
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = _LOCK_PATH.open("w", encoding="utf-8")
    try:
        logger.debug("Acquiring main-branch lock at %s", _LOCK_PATH)
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        logger.debug("Main-branch lock acquired")
        yield
    finally:
        fd.close()
        logger.debug("Main-branch lock released")
