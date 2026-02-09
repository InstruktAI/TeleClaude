"""Cron runner — discovers jobs and executes those whose configured schedule is due.

Two job types are supported:

1. **Python jobs** — modules in jobs/*.py that export a JOB instance.
2. **Agent jobs** — declared in teleclaude.yml with `type: agent`. The runner
   spawns a headless agent session via the daemon API. No Python module needed.

Scheduling configuration (frequency, preferred timing) lives in teleclaude.yml
under the `jobs:` key. The runner reads this config, evaluates whether each job
is due based on its last run timestamp and the configured schedule, and invokes
due jobs.

Jobs that have no entry in teleclaude.yml are skipped unless --force is used.
Jobs that have never run execute immediately on first discovery.
"""

from __future__ import annotations

import importlib
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from enum import Enum
from http.client import HTTPConnection
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

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


class JobConfig(TypedDict, total=False):
    schedule: str
    preferred_hour: int
    preferred_weekday: int
    preferred_day: int
    type: str
    script: str
    job: str
    agent: str
    thinking_mode: str
    message: str


def _load_job_schedules(config_path: Path | None = None) -> dict[str, JobConfig]:
    """Load job schedule configuration from teleclaude.yml."""
    if config_path is None:
        config_path = _REPO_ROOT / "teleclaude.yml"

    if not config_path.exists():
        logger.warning("teleclaude.yml not found", path=str(config_path))
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    jobs = config.get("jobs", {})
    if isinstance(jobs, dict):
        return jobs  # type: ignore[return-value]
    return {}


def _is_due(
    schedule_config: JobConfig,
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


_DAEMON_SOCKET = "/tmp/teleclaude-api.sock"


class _UnixSocketConnection(HTTPConnection):
    """HTTP connection over a Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


def _job_slug_to_spec_filename(job_slug: str) -> str:
    """Convert job slug to expected spec filename."""
    return f"{job_slug.replace('_', '-')}.md"


def _build_agent_job_message(job_name: str, config: JobConfig) -> str | None:
    """Build canonical job prompt from structured ``job`` config."""
    if "message" in config:
        logger.error("agent job uses deprecated message field", name=job_name)
        return None

    job_ref = str(config.get("job", "")).strip()
    if not job_ref:
        logger.error("agent job has no job field", name=job_name)
        return None

    spec_name = _job_slug_to_spec_filename(job_ref)
    return f"You are running the {job_name} job. Read @docs/project/spec/jobs/{spec_name} for your full instructions."


def _run_agent_job(job_name: str, config: JobConfig) -> bool:
    """Spawn a headless agent session for an agent-type job.

    Calls the daemon's POST /sessions endpoint via the unix socket.
    Fire-and-forget: the agent session runs to completion independently.
    """
    message = _build_agent_job_message(job_name, config)
    if not message:
        return False

    agent = str(config.get("agent", "claude"))
    thinking_mode = str(config.get("thinking_mode", "fast"))
    project_path = str(_REPO_ROOT)

    payload = json.dumps(
        {
            "computer": "local",
            "project_path": project_path,
            "title": job_name,
            "agent": agent,
            "thinking_mode": thinking_mode,
            "launch_kind": "agent_then_message",
            "message": message,
        }
    )

    try:
        conn = _UnixSocketConnection(_DAEMON_SOCKET)
        conn.request("POST", "/sessions", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = json.loads(resp.read().decode())
        conn.close()

        if resp.status != 200 or body.get("status") != "success":
            error = body.get("detail") or body.get("message") or "unknown error"
            logger.error("agent job session creation failed", name=job_name, error=error)
            return False

        session_id = body.get("session_id", "?")
        logger.info("agent job session spawned", name=job_name, session_id=session_id[:8])
        return True

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
        if str(config.get("type", "")) == "agent" and name not in python_job_names:
            all_job_names.append(name)

    logger.info("checking jobs", count=len(all_job_names), force=force, dry_run=dry_run)

    for job_name in all_job_names:
        if job_filter and job_name != job_filter:
            continue

        schedule_config = schedules.get(job_name)
        is_agent_job = schedule_config and str(schedule_config.get("type", "")) == "agent"

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

        schedule_name = schedule_config.get("schedule", "?") if schedule_config else "forced"
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
