"""Cron runner — discovers jobs and executes those whose configured schedule is due.

Two job types are supported:

1. **Python jobs** — modules in jobs/*.py that export a JOB instance.
2. **Agent jobs** — declared in teleclaude.yml with `type: agent`. The runner
   spawns a full interactive agent subprocess via run_job(). No daemon required.

Scheduling configuration (frequency, preferred timing) lives in teleclaude.yml
under the `jobs:` key. The runner reads this config, evaluates whether each job
is due based on its last run timestamp and the configured schedule, and invokes
due jobs.

Jobs that have no entry in teleclaude.yml are skipped unless --force is used.
Jobs that have never run execute immediately on first discovery.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import JobScheduleConfig
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


def _load_job_schedules(config_path: Path | None = None) -> dict[str, JobScheduleConfig]:
    """Load job schedule configuration from teleclaude.yml."""
    if config_path is None:
        config_path = _REPO_ROOT / "teleclaude.yml"

    config = load_project_config(config_path)
    return config.jobs


def _parse_duration(duration: str) -> timedelta:
    """Parse duration string (e.g., '10m', '2h', '1d') into timedelta."""
    match = re.match(r"^(\d+)([mhd])$", duration)
    if not match:
        raise ValueError(f"Invalid duration format: {duration}")
    value, unit = match.groups()
    value = int(value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    return timedelta()


def _is_due(
    schedule_config: JobScheduleConfig,
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

    # New 'when' scheduling contract
    if schedule_config.when:
        when = schedule_config.when
        if when.every:
            duration = _parse_duration(when.every)
            return elapsed >= duration

        if when.at:
            local_now = now.astimezone()  # System local time

            # Weekdays filter
            if when.weekdays:
                day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
                if local_now.weekday() not in [day_map[d] for d in when.weekdays]:
                    return False

            times_str = [when.at] if isinstance(when.at, str) else when.at
            for at_time_str in times_str:
                try:
                    at_hour, at_min = map(int, at_time_str.split(":"))
                    # Most recent scheduled occurrence of this time
                    scheduled_today = local_now.replace(hour=at_hour, minute=at_min, second=0, microsecond=0)
                    if local_now >= scheduled_today:
                        # Due if hasn't run today after scheduled time
                        if last_run.astimezone() < scheduled_today:
                            return True
                except (ValueError, AttributeError):
                    logger.error("invalid time format in config", at=at_time_str)
            return False

    # Legacy compatibility fallback
    schedule_str = schedule_config.schedule if schedule_config.schedule else "daily"
    # Ensure it matches Enum if it's a string from pydantic (which it should be)
    try:
        schedule = Schedule(schedule_str)
    except ValueError:
        schedule = Schedule.DAILY

    preferred_hour = schedule_config.preferred_hour
    preferred_weekday = schedule_config.preferred_weekday
    preferred_day = schedule_config.preferred_day

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


_DEFAULT_JOB_TIMEOUT_S = 1800  # 30 minutes


def _job_slug_to_spec_filename(job_slug: str) -> str:
    """Convert job slug to expected spec filename."""
    return f"{job_slug.replace('_', '-')}.md"


def _build_agent_job_message(job_name: str, config: JobScheduleConfig) -> str | None:
    """Build canonical job prompt from structured ``job`` config."""
    if config.message:
        logger.error("agent job uses deprecated message field", name=job_name)
        return None

    job_ref = str(config.job or "").strip()
    if not job_ref:
        logger.error("agent job has no job field", name=job_name)
        return None

    spec_name = _job_slug_to_spec_filename(job_ref)
    return f"You are running the {job_name} job. Read @docs/project/spec/jobs/{spec_name} for your full instructions."


def _run_agent_job(job_name: str, config: JobScheduleConfig) -> bool:
    """Spawn an agent subprocess for an agent-type job.

    Uses run_job() from agent_cli to spawn a full interactive agent subprocess
    with tools and MCP enabled. Blocks until the agent completes or times out.
    """
    from teleclaude.helpers.agent_cli import run_job

    message = _build_agent_job_message(job_name, config)
    if not message:
        return False

    agent = str(config.agent or "claude")
    thinking_mode = str(config.thinking_mode or "fast")
    timeout_s = config.timeout if config.timeout is not None else _DEFAULT_JOB_TIMEOUT_S

    try:
        exit_code = run_job(
            agent=agent,
            thinking_mode=thinking_mode,
            prompt=message,
            role="admin",
            timeout_s=timeout_s,
        )
        if exit_code == 0:
            logger.info("agent job completed", name=job_name)
            return True
        logger.error("agent job failed", name=job_name, exit_code=exit_code)
        return False

    except subprocess.TimeoutExpired:
        logger.error("agent job timed out", name=job_name, timeout_s=timeout_s)
        return False
    except Exception as e:
        logger.error("agent job dispatch failed", name=job_name, error=str(e))
        return False


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

    Supports two job types:
    - Python jobs: discovered from jobs/*.py modules
    - Agent jobs: declared in teleclaude.yml with ``type: agent``

    Args:
        force: Run jobs regardless of schedule
        job_filter: Only run job with this name
        dry_run: Check what would run without executing

    Returns:
        Dict mapping job name to success status
    """
    state = CronState.load()
    python_jobs = discover_jobs()
    schedules = _load_job_schedules()
    now = datetime.now(timezone.utc)
    results: dict[str, bool] = {}

    # Build a unified job list: Python modules + agent jobs from config
    python_job_names = {job.name for job in python_jobs}

    # Collect all job names to process (Python + agent-type from config)
    all_job_names: list[str] = [job.name for job in python_jobs]
    for name, config in schedules.items():
        if config.type == "agent" and name not in python_job_names:
            all_job_names.append(name)

    logger.info("checking jobs", count=len(all_job_names), force=force, dry_run=dry_run)

    for job_name in all_job_names:
        if job_filter and job_name != job_filter:
            continue

        schedule_config = schedules.get(job_name)
        is_agent_job = schedule_config and schedule_config.type == "agent"

        if not schedule_config and not force:
            logger.debug("job has no schedule config, skipping", name=job_name)
            continue

        job_state = state.get_job(job_name)

        if force:
            is_due = True
        elif schedule_config:
            is_due = _is_due(schedule_config, job_state.last_run, now)
        else:
            is_due = False

        if not is_due:
            logger.debug("job not due", name=job_name, last_run=job_state.last_run)
            continue

        schedule_name = (schedule_config.schedule or "?") if schedule_config else "forced"
        logger.info("job due", name=job_name, schedule=schedule_name, type="agent" if is_agent_job else "python")

        if dry_run:
            results[job_name] = True
            continue

        if is_agent_job:
            # Agent job: spawn headless session via daemon API
            success = _run_agent_job(job_name, schedule_config)  # type: ignore[arg-type]
            if success:
                state.mark_success(job_name)
            else:
                state.mark_failed(job_name, "agent session spawn failed")
            results[job_name] = success
        else:
            # Python job: find and execute the module
            python_job = next((j for j in python_jobs if j.name == job_name), None)
            if not python_job:
                logger.error("python job module not found", name=job_name)
                results[job_name] = False
                continue

            try:
                result = python_job.run()
                if result.success:
                    state.mark_success(job_name)
                    logger.info(
                        "job completed",
                        name=job_name,
                        message=result.message,
                        items=result.items_processed,
                    )
                else:
                    state.mark_failed(job_name, result.message)
                    logger.error(
                        "job failed",
                        name=job_name,
                        message=result.message,
                        errors=result.errors,
                    )
                results[job_name] = result.success

            except Exception as e:
                state.mark_failed(job_name, str(e))
                logger.exception("job error", name=job_name, error=str(e))
                results[job_name] = False

    return results
