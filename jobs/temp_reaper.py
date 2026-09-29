#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "instruktai-python-logger",
# ]
# ///
"""Reap orphaned TeleClaude unit sockets from /tmp.

Claude Code's per-session temp directories are not reaped here: they are
removed when their TeleClaude session closes (teleclaude/core/session_cleanup.py).

Integration:
- Called by the cron runner (scripts/cron_runner.py); cadence is owned by the
  ``temp-reaper`` entry in teleclaude.yml.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jobs.base import Job, JobResult, JobRunContext, run_job_cli

logger = get_logger(__name__)

_NOTHING_TO_REAP_MESSAGE = "Nothing to reap"
_REAPED_MESSAGE_TEMPLATE = "Removed {sockets} orphaned sockets"


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
    """Reap orphaned TeleClaude unit sockets."""

    def run(self, context: JobRunContext | None = None) -> JobResult:
        """Find and remove orphaned sockets."""
        del context
        sockets_removed = _reap_orphaned_sockets()
        if sockets_removed == 0:
            return JobResult(success=True, message=_NOTHING_TO_REAP_MESSAGE, items_processed=0)

        msg = _REAPED_MESSAGE_TEMPLATE.format(sockets=sockets_removed)
        logger.info(msg)
        return JobResult(success=True, message=msg, items_processed=sockets_removed)


JOB = TempReaperJob()


if __name__ == "__main__":
    raise SystemExit(run_job_cli(JOB))
