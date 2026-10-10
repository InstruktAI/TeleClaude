"""One full-native lint slot per shared Git repository."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.git import Repo
from teleclaude.runtime.command_runner import raise_if_command_cancelled

_LOCK_FILE = "teleclaude-full-native.lock"
_LOCK_MODE = "a"
_POLL_SECONDS = 0.05
_SLOT_RELEASED_EVENT = "quality_full_native_slot_released"

logger = get_logger(__name__)


@contextmanager
def full_native_slot(execution_root: Path) -> Iterator[None]:
    """Serialize full suites without sharing validation results or stale locks."""
    common_root = Path(Repo(execution_root, search_parent_directories=True).common_dir).resolve()
    root_id = sha256(os.fsencode(common_root)).hexdigest()
    queued_at = perf_counter()
    with (common_root / _LOCK_FILE).open(_LOCK_MODE) as handle:
        while True:
            raise_if_command_cancelled()
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(_POLL_SECONDS)
        acquired_at = perf_counter()
        try:
            raise_if_command_cancelled()
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            logger.debug(
                _SLOT_RELEASED_EVENT,
                repository_id=root_id,
                pid=os.getpid(),
                wait_ms=round((acquired_at - queued_at) * 1000),
                execution_ms=round((perf_counter() - acquired_at) * 1000),
            )
