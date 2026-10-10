"""One full-native lint slot per shared Git repository."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.git import Repo
from teleclaude.runtime.command_runner import ProcessGroupCancellationRequested, raise_if_command_cancelled

_LOCK_FILE = "teleclaude-full-native.lock"
_LOCK_MODE = "a"
_POLL_SECONDS = 0.05
_SLOT_COMPLETED_EVENT = "quality_full_native_slot_completed"

logger = get_logger(__name__)


class NativeSlotOutcome(StrEnum):
    """Completion states of slot coordination, independent of lint findings."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@contextmanager
def full_native_slot(execution_root: Path) -> Iterator[None]:
    """Serialize full suites without sharing validation results or stale locks."""
    common_root = Path(Repo(execution_root, search_parent_directories=True).common_dir).resolve()
    root_id = sha256(os.fsencode(common_root)).hexdigest()
    queued_at = perf_counter()
    acquired_at: float | None = None
    outcome = NativeSlotOutcome.ERROR
    try:
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
                outcome = NativeSlotOutcome.COMPLETED
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except ProcessGroupCancellationRequested:
        outcome = NativeSlotOutcome.CANCELLED
        raise
    finally:
        finished_at = perf_counter()
        log_completion = logger.error if outcome == NativeSlotOutcome.ERROR else logger.debug
        log_completion(
            _SLOT_COMPLETED_EVENT,
            repository_id=root_id,
            pid=os.getpid(),
            outcome=outcome,
            wait_ms=round(((finished_at if acquired_at is None else acquired_at) - queued_at) * 1000),
            execution_ms=0 if acquired_at is None else round((finished_at - acquired_at) * 1000),
        )
