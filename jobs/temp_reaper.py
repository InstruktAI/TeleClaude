"""Reap stale Claude Code temp files.

Claude Code writes background task outputs and tool results to
/tmp/claude-{UID}/ (Linux) or /private/tmp/claude-{UID}/ (macOS).
These files are never cleaned up by Claude Code itself, and macOS
does not auto-clean /tmp while the system is running. In multi-agent
environments this can accumulate to 100GB+ in days.

This job finds and removes files older than a configurable threshold.
It runs hourly and is safe to run while sessions are active — only
files older than the threshold are removed, and empty directories
are pruned afterward.

Integration:
- Called by the cron runner (scripts/cron_runner.py) on an hourly schedule.
- Config key: ``jobs.temp_reaper`` in teleclaude.yml.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

from instrukt_ai_logging import get_logger

from jobs.base import Job, JobResult

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = get_logger(__name__)

# Files older than this (in seconds) are reaped. 1 hour is safe —
# active sessions write continuously, so their files stay fresh.
_MAX_AGE_SECONDS = 3600


def _find_claude_temp_dir() -> Path | None:
    """Locate the Claude Code temp directory for the current user."""
    uid = os.getuid()
    candidates = [
        Path(f"/private/tmp/claude-{uid}"),  # macOS
        Path(f"/tmp/claude-{uid}"),  # Linux
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _reap_stale_files(root: Path, max_age: int) -> tuple[int, int]:
    """Remove files older than max_age seconds under root.

    Returns (files_removed, bytes_freed).
    """
    cutoff = time.time() - max_age
    files_removed = 0
    bytes_freed = 0

    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            filepath = Path(dirpath) / filename
            try:
                stat = filepath.stat()
                if stat.st_mtime < cutoff:
                    size = stat.st_size
                    filepath.unlink()
                    files_removed += 1
                    bytes_freed += size
            except (OSError, FileNotFoundError):
                continue

    return files_removed, bytes_freed


def _prune_empty_dirs(root: Path) -> int:
    """Remove empty directories under root (bottom-up). Does not remove root itself."""
    dirs_removed = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        path = Path(dirpath)
        if path == root:
            continue
        if not filenames and not dirnames:
            try:
                path.rmdir()
                dirs_removed += 1
            except OSError:
                continue
        # Update parent's dirnames list for accurate emptiness check
        dirnames[:] = [d for d in dirnames if (Path(dirpath) / d).exists()]
    return dirs_removed


def _reap_orphaned_sockets() -> int:
    """Remove orphaned teleclaude-unit-*.sock files from /tmp.

    Unit worker processes create Unix sockets but don't always clean
    them up on shutdown. We remove sockets whose PID (embedded in the
    filename) is no longer running.
    """
    tmp_dir = Path("/private/tmp") if platform.system() == "Darwin" else Path("/tmp")
    removed = 0

    for sock in tmp_dir.glob("teleclaude-unit-*.sock"):
        # Filename format: teleclaude-unit-{pid}-{hash}.sock
        parts = sock.name.split("-")
        if len(parts) >= 3:
            try:
                pid = int(parts[2])
                os.kill(pid, 0)  # Check if process exists (signal 0 = no-op)
            except (ValueError, ProcessLookupError):
                # PID not running or not a valid PID — orphaned socket
                try:
                    sock.unlink()
                    removed += 1
                except OSError:
                    continue
            except PermissionError:
                # Process exists but owned by another user — leave it
                continue

    return removed


class TempReaperJob(Job):
    """Reap stale Claude Code temp files and orphaned sockets."""

    name = "temp_reaper"

    def run(self) -> JobResult:
        """Find and remove stale temp files."""
        temp_dir = _find_claude_temp_dir()

        files_removed = 0
        bytes_freed = 0
        dirs_removed = 0
        sockets_removed = 0

        if temp_dir:
            logger.info("Reaping stale files from %s (max age: %ds)", temp_dir, _MAX_AGE_SECONDS)
            files_removed, bytes_freed = _reap_stale_files(temp_dir, _MAX_AGE_SECONDS)
            dirs_removed = _prune_empty_dirs(temp_dir)

        sockets_removed = _reap_orphaned_sockets()

        total_items = files_removed + dirs_removed + sockets_removed

        if total_items == 0:
            return JobResult(success=True, message="Nothing to reap", items_processed=0)

        mb_freed = bytes_freed / (1024 * 1024)
        msg = (
            f"Reaped {files_removed} files ({mb_freed:.1f}MB), "
            f"pruned {dirs_removed} empty dirs, "
            f"removed {sockets_removed} orphaned sockets"
        )
        logger.info(msg)
        return JobResult(success=True, message=msg, items_processed=total_items)


JOB = TempReaperJob()
