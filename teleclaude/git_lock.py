"""Process-level flock for main-branch git mutations.

Serializes concurrent bookkeeping commits and integration pushes
to prevent push races and index.lock conflicts on origin/main.
"""

from __future__ import annotations

import asyncio
import fcntl
import subprocess
import time
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.paths import GIT_MAIN_LOCK_PATH

logger = get_logger(__name__)

_LOCK_PATH = GIT_MAIN_LOCK_PATH


# ---------------------------------------------------------------------------
# .git/index.lock recovery
# ---------------------------------------------------------------------------
# A git process that is killed (any signal) between creating .git/index.lock
# and atomic-renaming it to .git/index leaves the lock file behind. There is
# no kernel-level cleanup — the next git invocation that touches the index
# fails with "fatal: Unable to create '.git/index.lock': File exists." This
# was the recurring failure mode driving the observability work; the function
# below resolves it without manual intervention.
#
# Fast path: lsof finds no holder AND mtime ≥ LSOF_GRACE → orphan, remove.
# Slow path: mtime ≥ AGE_CEILING → unconditional remove (covers a hung
#            process that still holds the fd but will never release).
# Otherwise: wait POLL_INTERVAL and retry.

INDEX_LOCK_LSOF_GRACE_SEC = 10
INDEX_LOCK_AGE_CEILING_SEC = 180
INDEX_LOCK_POLL_INTERVAL_SEC = 5


def _lsof_holders(path: Path) -> list[str]:
    """Return PIDs holding the given path open, or [] if none.

    Empty list means no process has the file open — the canonical orphan
    signal. lsof exits non-zero when there are no matches; that's expected
    and is reported as "no holders" rather than an error.
    """
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-t", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        # No lsof available, or lsof hung — treat as "unknown holders" so
        # callers fall back to the age ceiling instead of falsely declaring
        # the lock orphaned.
        logger.warning("lsof_unavailable path=%s err=%s", path, exc)
        return ["unknown"]
    pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return pids


def wait_for_index_lock_clear(project_root: Path) -> None:
    """Block until .git/index.lock is gone or safe to remove.

    Polls every POLL_INTERVAL seconds. Returns normally once the lock is
    clear (either gone naturally or removed as stale by this function).
    Raises nothing; the worst case is unconditional removal at the age
    ceiling, which is logged at WARNING with full context.

    Note: only checks the repo-root index lock at <project_root>/.git/
    index.lock. Worktree index locks (under .git/worktrees/<n>/index.lock)
    are not considered — the file is the documented failure surface for
    main-branch commits.
    """
    lock_path = project_root / ".git" / "index.lock"
    started = time.monotonic()
    while lock_path.exists():
        try:
            stat = lock_path.stat()
        except FileNotFoundError:
            return  # Cleared between exists() and stat().
        age_s = time.time() - stat.st_mtime
        size_b = stat.st_size
        holders = _lsof_holders(lock_path)

        if not holders and age_s >= INDEX_LOCK_LSOF_GRACE_SEC:
            logger.warning(
                "stale_index_lock_removed path=%s age_s=%.1f size_b=%d reason=lsof_empty",
                lock_path,
                age_s,
                size_b,
            )
            lock_path.unlink(missing_ok=True)
            return

        if age_s >= INDEX_LOCK_AGE_CEILING_SEC:
            logger.warning(
                "stale_index_lock_removed path=%s age_s=%.1f size_b=%d reason=age_ceiling holders=%s",
                lock_path,
                age_s,
                size_b,
                holders,
            )
            lock_path.unlink(missing_ok=True)
            return

        elapsed = time.monotonic() - started
        logger.info(
            "index_lock_busy path=%s age_s=%.1f size_b=%d holders=%s waited_s=%.1f; retrying in %ds",
            lock_path,
            age_s,
            size_b,
            holders,
            elapsed,
            INDEX_LOCK_POLL_INTERVAL_SEC,
        )
        time.sleep(INDEX_LOCK_POLL_INTERVAL_SEC)


@contextmanager
def main_branch_lock() -> Generator[None, None, None]:
    """Acquire an exclusive flock on the main-branch lock file, blocking until it is acquired.

    The lock is released when the context manager exits (fd closed → flock released).
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


@asynccontextmanager
async def main_branch_lock_async() -> AsyncIterator[None]:
    """Hold the shared Git mutation lock without blocking the event loop."""
    lock_context = main_branch_lock()
    acquire_task = asyncio.create_task(asyncio.to_thread(lock_context.__enter__))
    try:
        await asyncio.shield(acquire_task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(acquire_task)
        except BaseException:
            raise
        release_task = asyncio.create_task(asyncio.to_thread(lock_context.__exit__, None, None, None))
        await asyncio.shield(release_task)
        raise
    try:
        yield
    finally:
        release_task = asyncio.create_task(asyncio.to_thread(lock_context.__exit__, None, None, None))
        await asyncio.shield(release_task)
