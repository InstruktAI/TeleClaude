"""Cron runner — discovers jobs and executes those whose configured schedule is due.

Job modules in jobs/*.py define what work to do. Scheduling configuration
(frequency, preferred timing) lives in teleclaude.yml under the `jobs:` key.
The runner reads this config, evaluates whether each job is due based on its
last run timestamp and the configured schedule, and invokes due jobs.

Jobs that have no entry in teleclaude.yml are skipped unless --force is used.
Jobs that have never run execute immediately on first discovery.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.cron.state import CronState

if TYPE_CHECKING:
    from jobs.base import Job

logger = get_logger(__name__)

# Ensure repo root is in path for job imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class Schedule(Enum):
    """Job schedule frequencies."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


def _load_job_schedules(config_path: Path | None = None) -> dict[str, dict[str, str | int]]:
    """Load job schedule configuration from teleclaude.yml."""
    if config_path is None:
        config_path = _REPO_ROOT / "teleclaude.yml"

    if not config_path.exists():
        logger.warning("teleclaude.yml not found", path=str(config_path))
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    return config.get("jobs", {})


def _is_due(
    schedule_config: dict[str, str | int],
    last_run: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Check if a job is due based on its teleclaude.yml schedule config."""
    if now is None:
        now = datetime.now(timezone.utc)

    if last_run is None:
        return True

    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)

    elapsed = now - last_run
    schedule = Schedule(schedule_config.get("schedule", "daily"))
    preferred_hour = int(schedule_config.get("preferred_hour", 6))
    preferred_weekday = int(schedule_config.get("preferred_weekday", 0))
    preferred_day = int(schedule_config.get("preferred_day", 1))

    match schedule:
        case Schedule.HOURLY:
            return elapsed >= timedelta(hours=1)

        case Schedule.DAILY:
            if elapsed < timedelta(hours=20):
                return False
            return now.hour >= preferred_hour

        case Schedule.WEEKLY:
            if elapsed < timedelta(days=6):
                return False
            return now.weekday() == preferred_weekday and now.hour >= preferred_hour

        case Schedule.MONTHLY:
            if elapsed < timedelta(days=25):
                return False
            return now.day == preferred_day and now.hour >= preferred_hour


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
    Run all jobs that are due based on their teleclaude.yml schedule.

    Args:
        force: Run jobs regardless of schedule
        job_filter: Only run job with this name
        dry_run: Check what would run without executing

    Returns:
        Dict mapping job name to success status
    """
    state = CronState.load()
    jobs = discover_jobs()
    schedules = _load_job_schedules()
    now = datetime.now(timezone.utc)
    results: dict[str, bool] = {}

    logger.info("checking jobs", count=len(jobs), force=force, dry_run=dry_run)

    for job in jobs:
        # Filter by name if specified
        if job_filter and job.name != job_filter:
            continue

        # Check schedule config exists
        schedule_config = schedules.get(job.name)
        if not schedule_config and not force:
            logger.debug("job has no schedule config, skipping", name=job.name)
            continue

        job_state = state.get_job(job.name)

        if force:
            is_due = True
        elif schedule_config:
            is_due = _is_due(schedule_config, job_state.last_run, now)
        else:
            is_due = False

        if not is_due:
            logger.debug("job not due", name=job.name, last_run=job_state.last_run)
            continue

        schedule_name = schedule_config.get("schedule", "?") if schedule_config else "forced"
        logger.info("job due", name=job.name, schedule=schedule_name)

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
