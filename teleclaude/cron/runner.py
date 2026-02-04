"""Cron runner - discovers and executes due jobs."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cron.state import CronState

if TYPE_CHECKING:
    from jobs.base import Job

logger = get_logger(__name__)

# Ensure repo root is in path for job imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def discover_jobs(jobs_dir: Path | None = None) -> list[Job]:
    """
    Discover all job definitions from the jobs/ directory.

    Each job module should export a JOB instance.
    """
    if jobs_dir is None:
        jobs_dir = _REPO_ROOT / "jobs"

    jobs: list[Job] = []

    if not jobs_dir.is_dir():
        logger.warning("jobs directory not found", path=str(jobs_dir))
        return jobs

    for job_file in sorted(jobs_dir.glob("*.py")):
        if job_file.name.startswith("_"):
            continue
        if job_file.name == "base.py":
            continue

        module_name = f"jobs.{job_file.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "JOB"):
                jobs.append(module.JOB)
                logger.debug("discovered job", name=module.JOB.name)
        except Exception as e:
            logger.error("failed to load job", module=module_name, error=str(e))

    return jobs


def run_due_jobs(
    *,
    force: bool = False,
    job_filter: str | None = None,
    dry_run: bool = False,
) -> dict[str, bool]:
    """
    Run all jobs that are due based on their schedule.

    Args:
        force: Run jobs regardless of schedule
        job_filter: Only run job with this name
        dry_run: Check what would run without executing

    Returns:
        Dict mapping job name to success status
    """
    state = CronState.load()
    jobs = discover_jobs()
    now = datetime.now(timezone.utc)
    results: dict[str, bool] = {}

    logger.info("checking jobs", count=len(jobs), force=force, dry_run=dry_run)

    for job in jobs:
        # Filter by name if specified
        if job_filter and job.name != job_filter:
            continue

        job_state = state.get_job(job.name)
        is_due = force or job.is_due(job_state.last_run, now)

        if not is_due:
            logger.debug("job not due", name=job.name, last_run=job_state.last_run)
            continue

        logger.info("job due", name=job.name, schedule=job.schedule.value)

        if dry_run:
            results[job.name] = True
            continue

        try:
            result = job.run()
            if result.success:
                state.mark_success(job.name)
                logger.info(
                    "job completed",
                    name=job.name,
                    message=result.message,
                    items=result.items_processed,
                )
            else:
                state.mark_failed(job.name, result.message)
                logger.error(
                    "job failed",
                    name=job.name,
                    message=result.message,
                    errors=result.errors,
                )
            results[job.name] = result.success

        except Exception as e:
            state.mark_failed(job.name, str(e))
            logger.exception("job error", name=job.name, error=str(e))
            results[job.name] = False

    return results
