"""Cron runner — discovers jobs and executes those whose configured schedule is due.

Two job types are supported:

1. **Script jobs** — standalone `uv run` scripts declared in teleclaude.yml.
2. **Agent jobs** — declared in teleclaude.yml with `type: agent`. The runner
   spawns a full interactive agent subprocess via run_job(). No daemon required.

Scheduling configuration (frequency, preferred timing) lives in teleclaude.yml
under the `jobs:` key. The runner reads this config, evaluates whether each job
is due based on its last run timestamp and the configured schedule, and invokes
due jobs.

Jobs that have no entry in teleclaude.yml are skipped unless --force is used.
Jobs that have never run wait for their first real scheduled occurrence after
discovery.
"""

from __future__ import annotations

import asyncio
import atexit
import calendar
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

from instrukt_ai_logging import get_logger

from jobs.base import JobResult
from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron.notification_scan import find_undelivered_reports
from teleclaude.cron.state import CronState

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


def load_job_schedules(config_path: Path | None = None) -> dict[str, JobScheduleConfig]:
    """Load job schedule configuration from teleclaude.yml."""
    return _load_job_schedules(config_path)


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
        now = datetime.now(UTC)

    if last_run is None:
        return False

    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)

    elapsed = now - last_run

    if schedule_config.when:
        when_due = _is_when_due(schedule_config, last_run, now, elapsed)
        if when_due is not None:
            return when_due

    schedule_str = schedule_config.schedule if schedule_config.schedule else "daily"
    try:
        schedule = Schedule(schedule_str)
    except ValueError:
        schedule = Schedule.DAILY
    return _is_legacy_schedule_due(schedule, schedule_config, now, elapsed)


def _is_when_due(
    schedule_config: JobScheduleConfig,
    last_run: datetime,
    now: datetime,
    elapsed: timedelta,
) -> bool | None:
    when = schedule_config.when
    if not when:
        return None
    if when.every:
        return elapsed >= _parse_duration(when.every)
    if not when.at:
        return None
    local_now = now.astimezone()
    if not _is_allowed_weekday(local_now, when.weekdays):  # type: ignore[arg-type]
        return False
    for at_time_str in [when.at] if isinstance(when.at, str) else when.at:
        scheduled_today = _scheduled_occurrence(local_now, at_time_str)
        if scheduled_today and last_run.astimezone() < scheduled_today <= local_now:
            return True
    return False


def _is_allowed_weekday(now: datetime, weekdays: list[str] | None) -> bool:
    if not weekdays:
        return True
    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    return now.weekday() in [day_map[day] for day in weekdays]


def _scheduled_occurrence(local_now: datetime, at_time_str: str) -> datetime | None:
    try:
        at_hour, at_min = map(int, at_time_str.split(":"))
        return local_now.replace(hour=at_hour, minute=at_min, second=0, microsecond=0)
    except (ValueError, AttributeError):
        logger.error("invalid time format in config", at=at_time_str)
        return None


def _next_daily_occurrence(after: datetime, preferred_hour: int) -> datetime:
    candidate = after.replace(hour=preferred_hour, minute=0, second=0, microsecond=0)
    if candidate < after:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly_occurrence(after: datetime, preferred_weekday: int, preferred_hour: int) -> datetime:
    day_delta = (preferred_weekday - after.weekday()) % 7
    candidate = (after + timedelta(days=day_delta)).replace(hour=preferred_hour, minute=0, second=0, microsecond=0)
    if candidate < after:
        candidate += timedelta(days=7)
    return candidate


def _next_monthly_occurrence(after: datetime, preferred_day: int, preferred_hour: int) -> datetime:
    year = after.year
    month = after.month
    while True:
        last_day = calendar.monthrange(year, month)[1]
        day = min(preferred_day, last_day)
        candidate = after.replace(year=year, month=month, day=day, hour=preferred_hour, minute=0, second=0, microsecond=0)
        if candidate >= after:
            return candidate
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def _is_first_run_due(
    schedule_config: JobScheduleConfig,
    first_seen_at: datetime | None,
    now: datetime,
) -> bool:
    if first_seen_at is None:
        return False

    if first_seen_at.tzinfo is None:
        first_seen_at = first_seen_at.replace(tzinfo=UTC)

    if schedule_config.when:
        when = schedule_config.when
        if when.every:
            return now - first_seen_at >= _parse_duration(when.every)
        if when.at:
            local_now = now.astimezone()
            local_first_seen = first_seen_at.astimezone()
            if not _is_allowed_weekday(local_now, when.weekdays):  # type: ignore[arg-type]
                return False
            for at_time_str in [when.at] if isinstance(when.at, str) else when.at:
                scheduled_today = _scheduled_occurrence(local_now, at_time_str)
                if scheduled_today and local_first_seen <= scheduled_today <= local_now:
                    return True
            return False

    schedule_str = schedule_config.schedule if schedule_config.schedule else "daily"
    try:
        schedule = Schedule(schedule_str)
    except ValueError:
        schedule = Schedule.DAILY

    local_first_seen = first_seen_at.astimezone()
    local_now = now.astimezone()

    match schedule:
        case Schedule.HOURLY:
            return local_now >= (local_first_seen + timedelta(hours=1))
        case Schedule.DAILY:
            next_run = _next_daily_occurrence(local_first_seen, schedule_config.preferred_hour)
        case Schedule.WEEKLY:
            next_run = _next_weekly_occurrence(
                local_first_seen,
                schedule_config.preferred_weekday,
                schedule_config.preferred_hour,
            )
        case Schedule.MONTHLY:
            next_run = _next_monthly_occurrence(
                local_first_seen,
                schedule_config.preferred_day,
                schedule_config.preferred_hour,
            )
    return local_now >= next_run


def _is_legacy_schedule_due(
    schedule: Schedule,
    schedule_config: JobScheduleConfig,
    now: datetime,
    elapsed: timedelta,
) -> bool:
    preferred_hour = schedule_config.preferred_hour
    preferred_weekday = schedule_config.preferred_weekday
    preferred_day = schedule_config.preferred_day
    match schedule:
        case Schedule.HOURLY:
            return elapsed >= timedelta(hours=1)
        case Schedule.DAILY:
            return elapsed >= timedelta(hours=20) and now.hour >= preferred_hour
        case Schedule.WEEKLY:
            return elapsed >= timedelta(days=6) and now.weekday() == preferred_weekday and now.hour >= preferred_hour
        case Schedule.MONTHLY:
            return elapsed >= timedelta(days=25) and now.day == preferred_day and now.hour >= preferred_hour


_DEFAULT_JOB_TIMEOUT_S = 1800  # 30 minutes
_PIDFILE = Path.home() / ".teleclaude" / "cron_runner.pid"


@dataclass(frozen=True)
class ScriptJob:
    """Configured standalone script job."""

    name: str
    script: str


def _acquire_pidlock() -> bool:
    """Acquire a pidfile lock. Returns True if acquired, False if another runner is alive."""
    if _PIDFILE.exists():
        try:
            old_pid = int(_PIDFILE.read_text().strip())
            os.kill(old_pid, 0)  # Check if process is alive
            return False  # Another runner is still running
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # Stale pidfile or unreadable — proceed

    _PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    _PIDFILE.write_text(str(os.getpid()))
    atexit.register(_release_pidlock)
    return True


def _release_pidlock() -> None:
    """Remove the pidfile on exit."""
    try:
        _PIDFILE.unlink(missing_ok=True)
    except OSError:
        pass


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
    """Trigger an agent job via the API (fire-and-forget session creation).

    Instead of spawning a subprocess directly, this sends a request to the daemon
    to create a session with job metadata. The daemon handles execution.
    """
    from teleclaude.cli.api_client import TelecAPIClient  # pylint: disable=import-outside-toplevel
    from teleclaude.config import config as global_config  # pylint: disable=import-outside-toplevel

    message = _build_agent_job_message(job_name, config)
    if not message:
        return False

    agent = str(config.agent or "claude")
    thinking_mode = str(config.thinking_mode or "fast")

    # Job sessions are always created on the local computer where the runner is active
    computer = global_config.computer.name
    # Project root is assumed to be current repo root
    project_path = str(_REPO_ROOT)

    async def _trigger() -> bool:
        client = TelecAPIClient()
        await client.connect()
        try:
            await client.create_session(
                computer=computer,
                project_path=project_path,
                agent=agent,
                thinking_mode=thinking_mode,
                title=f"Job: {job_name}",
                message=message,
                metadata={"system_role": "system", "job": job_name, "job_type": config.type or "agent"},
            )
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("agent job API trigger failed", name=job_name, error=str(e))
            return False
        finally:
            await client.close()

    try:
        return asyncio.run(_trigger())
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("agent job trigger crashed", name=job_name, error=str(e))
        return False


def _should_run_subscription_job(
    job_name: str,
    state: CronState,
    now: datetime,
    *,
    root: Path | None = None,
) -> bool:
    """Check if any subscriber's schedule makes a subscription job due.

    Iterates person configs for enabled JobSubscription entries matching
    *job_name* and checks if any subscriber's ``when`` schedule is due.
    """
    from teleclaude.config.loader import load_person_config  # pylint: disable=import-outside-toplevel
    from teleclaude.config.schema import JobSubscription  # pylint: disable=import-outside-toplevel

    if root is None:
        root = Path.home() / ".teleclaude"

    people_dir = root / "people"
    if not people_dir.is_dir():
        return False

    job_state = state.get_job(job_name)

    for person_dir in sorted(people_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        cfg_path = person_dir / "teleclaude.yml"
        if not cfg_path.exists():
            continue
        try:
            person_cfg = load_person_config(cfg_path)
        except Exception:  # pylint: disable=broad-exception-caught
            continue

        for sub in person_cfg.subscriptions:
            if not isinstance(sub, JobSubscription):
                continue
            if sub.job != job_name or not sub.enabled:
                continue
            # Found an enabled subscriber; check schedule
            if sub.when:
                schedule_cfg = JobScheduleConfig(when=sub.when)
                if job_state.last_run is None:
                    if _is_first_run_due(schedule_cfg, job_state.first_seen_at, now):
                        return True
                elif _is_due(schedule_cfg, job_state.last_run, now):
                    return True
            else:
                # No when config: always due if never run
                if job_state.last_run is None:
                    return True

    return False


def _scan_and_notify(
    state: CronState,
    schedules: dict[str, JobScheduleConfig],  # pylint: disable=unused-argument
    root: Path | None = None,
) -> None:
    """Scan for undelivered reports and mark them notified. Delivery is via event platform."""
    if root is None:
        root = Path.home() / ".teleclaude"

    jobs_dir = root / "jobs"
    undelivered = find_undelivered_reports(jobs_dir, state)

    if not undelivered:
        return

    for job_name, reports in undelivered.items():
        latest_mtime = datetime.min.replace(tzinfo=UTC)

        for report_path in reports:
            mtime = datetime.fromtimestamp(report_path.stat().st_mtime, tz=UTC)
            latest_mtime = max(latest_mtime, mtime)

        if latest_mtime > datetime.min.replace(tzinfo=UTC):
            logger.info("marking job reports notified (delivery via event platform)", job=job_name)
            state.mark_notified(job_name, latest_mtime)


def _resolve_script_path(script: str, root: Path | None = None) -> Path:
    if root is None:
        root = _REPO_ROOT
    path = Path(script)
    if not path.is_absolute():
        path = root / path
    return path


def discover_jobs(jobs_dir: Path | None = None) -> list[ScriptJob]:
    """Discover configured standalone script jobs from teleclaude.yml."""
    if jobs_dir is None:
        config_path = _REPO_ROOT / "teleclaude.yml"
    else:
        config_path = jobs_dir.parent / "teleclaude.yml"
    config_root = config_path.parent

    schedules = _load_job_schedules(config_path)
    jobs: list[ScriptJob] = []

    for name, config in schedules.items():
        script = str(config.script or "").strip()
        if not script:
            continue
        script_path = _resolve_script_path(script, root=config_root)
        if not script_path.exists():
            logger.error("configured job script not found", name=name, script=str(script_path))
            continue
        jobs.append(ScriptJob(name=name, script=script))
        logger.debug("discovered job", name=name, script=script)

    return jobs


def _parse_script_job_result(stdout: str) -> JobResult | None:
    for line in reversed(stdout.splitlines()):
        raw = line.strip()
        if not raw:
            continue
        try:
            return JobResult.from_json(raw)
        except ValueError:
            continue
    return None


def _run_script_job(job: ScriptJob, timeout_s: int | None = None) -> JobResult:
    script_path = _resolve_script_path(job.script)
    timeout = timeout_s or _DEFAULT_JOB_TIMEOUT_S

    try:
        completed = subprocess.run(
            ["uv", "run", "--quiet", str(script_path)],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return JobResult(success=False, message=f"{job.name} timed out after {timeout}s")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JobResult(success=False, message=f"{job.name} failed to start: {exc}")

    parsed = _parse_script_job_result(completed.stdout)
    if parsed is not None:
        return parsed

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    if completed.returncode == 0:
        message = stdout or stderr or f"{job.name} completed"
        return JobResult(success=True, message=message)

    detail = stderr or stdout or f"script exited with code {completed.returncode}"
    return JobResult(success=False, message=detail)


def run_due_jobs(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    *,
    force: bool = False,
    job_filter: str | None = None,
    dry_run: bool = False,
    root: Path | None = None,
) -> dict[str, bool]:
    """Run all jobs that are due based on their teleclaude.yml schedule.

    Supports two job types:

    - **Script jobs** — declared in ``teleclaude.yml`` with ``script`` entries.
    - **Agent jobs** — declared in ``teleclaude.yml`` with ``type: agent``.

    Subscription-category jobs are only run when at least one person has an
    enabled ``JobSubscription`` with a matching ``when`` schedule that is due.
    System-category jobs follow the schedule in ``teleclaude.yml`` directly.

    After execution, a notification scan discovers undelivered reports and
    enqueues outbox rows for each recipient.
    """
    if not _acquire_pidlock():
        logger.info("another cron runner is active, skipping")
        return {}

    state = CronState.load()
    script_jobs = discover_jobs()
    schedules = _load_job_schedules()
    now = datetime.now(UTC)
    results: dict[str, bool] = {}

    # Build a unified job list: Python modules + agent jobs from config
    script_job_names = {job.name for job in script_jobs}

    all_job_names: list[str] = [job.name for job in script_jobs]
    for name, config in schedules.items():
        if config.type == "agent" and name not in script_job_names:
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

        job_state = state.ensure_first_seen(job_name, now)

        # Determine if job is due
        if force:
            is_due = True
        elif schedule_config and schedule_config.category == "subscription":
            is_due = _should_run_subscription_job(job_name, state, now, root=root)
        elif schedule_config:
            if job_state.last_run is None:
                is_due = _is_first_run_due(schedule_config, job_state.first_seen_at, now)
            else:
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
            success = _run_agent_job(job_name, schedule_config)
            if success:
                state.mark_success(job_name)
            else:
                state.mark_failed(job_name, "agent session spawn failed")
            results[job_name] = success
        else:
            script_job = next((j for j in script_jobs if j.name == job_name), None)
            if not script_job:
                logger.error("script job not found", name=job_name)
                results[job_name] = False
                continue

            try:
                result = _run_script_job(script_job, timeout_s=schedule_config.timeout if schedule_config else None)
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

            except Exception as e:  # pylint: disable=broad-exception-caught
                state.mark_failed(job_name, str(e))
                logger.exception("job error", name=job_name, error=str(e))
                results[job_name] = False

    # Post-execution: scan for undelivered reports and enqueue notifications
    if not dry_run:
        try:
            _scan_and_notify(state, schedules, root=root)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("notification scan failed", error=str(exc))

    return results
