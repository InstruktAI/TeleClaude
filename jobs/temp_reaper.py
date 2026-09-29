#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "instruktai-python-logger",
# ]
# ///
"""Reap idle Claude Code temp directories.

Claude Code writes per-session scratchpads and background task outputs to
/tmp/claude-{UID}/ (Linux) or /private/tmp/claude-{UID}/ (macOS), laid out as
``<project-slug>/<session-id>/``. Claude Code never cleans these up, and macOS
does not auto-clean /tmp while the system is running. In multi-agent
environments this can accumulate to 100GB+ in days.

The reaping unit is a whole directory two levels below the temp root — a
session directory, or an entry of another tool directory. A unit is removed
only once it has been idle for longer than ``_MAX_IDLE_SECONDS``, where
activity is the newest mtime anywhere in the unit and, for a Claude session,
the mtime of its transcript. A live session's scratchpad is therefore never
touched, however old the individual files in it are.

Integration:
- Called by the cron runner (scripts/cron_runner.py); cadence is owned by the
  ``temp-reaper`` entry in teleclaude.yml.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from instrukt_ai_logging import get_logger

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jobs.base import Job, JobResult, JobRunContext, run_job_cli

logger = get_logger(__name__)

# A unit untouched for this long belongs to an ended session. The transcript
# check keeps an idle-but-open session alive for this whole window.
_MAX_IDLE_SECONDS = 24 * 3600

_CLAUDE_TRANSCRIPTS_DIR = Path.home() / ".claude" / "projects"
_TRANSCRIPT_SUFFIX = ".jsonl"

_REAPING_EVENT = "reaping idle temp units"
_UNIT_REAP_FAILED_EVENT = "temp unit reap failed"
_UNIT_REAP_FAILED_TEMPLATE = "{unit}: {error}"
_NOTHING_TO_REAP_MESSAGE = "Nothing to reap"
_REAPED_MESSAGE_TEMPLATE = (
    "Reaped {units} idle units ({mb:.1f}MB), pruned {dirs} empty dirs, removed {sockets} orphaned sockets"
)


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


def _tree_stats(unit: Path) -> tuple[float, int]:
    """Return (newest mtime, total file bytes) over unit and everything beneath it.

    Directory mtimes count as activity, so a freshly created empty scratchpad
    keeps its unit alive.
    """
    latest = unit.lstat().st_mtime
    size = 0
    for dirpath, dirnames, filenames in os.walk(unit):
        for name in dirnames:
            with contextlib.suppress(FileNotFoundError):
                latest = max(latest, (Path(dirpath) / name).lstat().st_mtime)
        for name in filenames:
            with contextlib.suppress(FileNotFoundError):
                stat = (Path(dirpath) / name).lstat()
                latest = max(latest, stat.st_mtime)
                size += stat.st_size
    return latest, size


def _transcript_mtime(unit: Path) -> float | None:
    """Return the mtime of the Claude transcript for a session unit, if one exists."""
    transcript = _CLAUDE_TRANSCRIPTS_DIR / unit.parent.name / (unit.name + _TRANSCRIPT_SUFFIX)
    try:
        return transcript.stat().st_mtime
    except FileNotFoundError:
        return None


@dataclass
class _ReapOutcome:
    units_removed: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list[str])


def _iter_units(root: Path) -> list[Path]:
    """List the reaping units under root: <root>/<project-slug>/<session-id> for
    sessions, <root>/<tool>/<entry> otherwise.

    Symlinks are skipped at both levels so no unit resolves outside root.
    """
    units: list[Path] = []
    for parent in root.iterdir():
        if parent.is_symlink() or not parent.is_dir():
            continue
        units.extend(unit for unit in parent.iterdir() if not unit.is_symlink() and unit.is_dir())
    return units


def _reap_idle_units(root: Path, max_idle: int) -> _ReapOutcome:
    """Remove every unit under root that has been idle for longer than max_idle seconds."""
    cutoff = time.time() - max_idle
    outcome = _ReapOutcome()

    for unit in _iter_units(root):
        try:
            latest, size = _tree_stats(unit)
            transcript_mtime = _transcript_mtime(unit)
            if transcript_mtime is not None:
                latest = max(latest, transcript_mtime)
            if latest >= cutoff:
                continue
            shutil.rmtree(unit)
        except OSError as exc:
            logger.warning(_UNIT_REAP_FAILED_EVENT, unit=str(unit), error=str(exc))
            outcome.errors.append(_UNIT_REAP_FAILED_TEMPLATE.format(unit=unit, error=exc))
            continue
        outcome.units_removed += 1
        outcome.bytes_freed += size

    return outcome


def _prune_empty_parents(root: Path) -> int:
    """Remove empty directories directly under root. Units below them are never pruned."""
    dirs_removed = 0
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            child.rmdir()
        except OSError:
            # Not empty, or a unit was created concurrently: leave it.
            continue
        dirs_removed += 1
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
    """Reap idle Claude Code temp directories and orphaned sockets."""

    def run(self, context: JobRunContext | None = None) -> JobResult:
        """Find and remove idle temp directories."""
        del context
        temp_dir = _find_claude_temp_dir()

        outcome = _ReapOutcome()
        dirs_removed = 0
        sockets_removed = 0

        if temp_dir:
            logger.info(_REAPING_EVENT, root=str(temp_dir), max_idle_seconds=_MAX_IDLE_SECONDS)
            outcome = _reap_idle_units(temp_dir, _MAX_IDLE_SECONDS)
            dirs_removed = _prune_empty_parents(temp_dir)

        sockets_removed = _reap_orphaned_sockets()

        total_items = outcome.units_removed + dirs_removed + sockets_removed

        if total_items == 0 and not outcome.errors:
            return JobResult(success=True, message=_NOTHING_TO_REAP_MESSAGE, items_processed=0)

        msg = _REAPED_MESSAGE_TEMPLATE.format(
            units=outcome.units_removed,
            mb=outcome.bytes_freed / (1024 * 1024),
            dirs=dirs_removed,
            sockets=sockets_removed,
        )
        logger.info(msg)
        return JobResult(
            success=not outcome.errors,
            message=msg,
            items_processed=total_items,
            errors=outcome.errors or None,
        )


JOB = TempReaperJob()


if __name__ == "__main__":
    raise SystemExit(run_job_cli(JOB))
