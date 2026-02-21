"""Scan for undelivered job reports using the mailbox-flag pattern."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cron.state import CronState

logger = get_logger(__name__)


def find_undelivered_reports(
    jobs_dir: Path,
    state: CronState,
) -> dict[str, list[Path]]:
    """Find job reports that have not yet been notified.

    Globs ``jobs_dir/*/runs/*.md`` and compares file mtime to
    ``last_notified`` in *state*.  Reports with mtime after last_notified
    (or when last_notified is None) are considered undelivered.

    Returns a mapping of job name -> list of undelivered report paths.
    """
    if not jobs_dir.is_dir():
        return {}

    result: dict[str, list[Path]] = {}

    for report_path in sorted(jobs_dir.glob("*/runs/*.md")):
        job_name = report_path.parent.parent.name
        job_state = state.get_job(job_name)

        mtime = datetime.fromtimestamp(report_path.stat().st_mtime, tz=timezone.utc)

        if job_state.last_notified is None or mtime > job_state.last_notified:
            result.setdefault(job_name, []).append(report_path)

    return result
