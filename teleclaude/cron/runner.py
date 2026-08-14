"""Cron runner — discovers jobs and executes those whose configured schedule is due.

Two job types are supported:

1. **Script jobs** — module-level `JOB` instances declared in teleclaude.yml.
2. **Agent jobs** — declared in teleclaude.yml with `type: agent`. The runner
   opens a run when it dispatches the session and closes it from a structured
   `telec jobs report` result.

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
import importlib
import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from queue import Queue
from typing import cast

from instrukt_ai_logging import get_logger

from jobs.base import Job, JobResult
from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config import config as global_config
from teleclaude.config.loader import load_person_config, load_project_config
from teleclaude.config.schema import JobScheduleConfig, JobSubscription
from teleclaude.constants import ROLE_JOB_RUNNER
from teleclaude.core.models import HumanActionIntent, Session
from teleclaude.cron.state import CronState, JobRunStatus, PendingEmission
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.producer import ensure_event_producer
from teleclaude.events.schemas.jobs import JobRunEventType
from teleclaude.paths import CRON_PID_PATH, JOBS_DIR, LOG_BUG_HUNTER_STATE_DIR, TELECLAUDE_HOME, ConfigFileName
from teleclaude.services.log_bug_hunter_service import LOG_BUG_HUNTER_JOB, LogBugHunterService
from teleclaude.services.project_catalog import ProjectNode, get_project_catalog_service
from teleclaude.services.project_jobs import ProjectJobOrchestrator
from teleclaude.types.commands import CreateSessionCommand

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
        config_path = _REPO_ROOT / ConfigFileName.OVERLAY

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
        candidate = after.replace(
            year=year, month=month, day=day, hour=preferred_hour, minute=0, second=0, microsecond=0
        )
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
_PIDFILE = CRON_PID_PATH


@dataclass(frozen=True)
class ScriptJob:
    """Configured standalone script job."""

    name: str
    script: str
    module_name: str


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


def _build_agent_job_message(job_name: str, config: JobScheduleConfig) -> str | None:
    """Build canonical job prompt from structured ``job`` config."""
    if config.message:
        logger.error("agent job uses deprecated message field", name=job_name)
        return None

    job_ref = str(config.job or "").strip()
    if not job_ref:
        logger.error("agent job has no job field", name=job_name)
        return None

    return f"/next-run-job {job_name}"


def _run_agent_job(job_name: str, config: JobScheduleConfig) -> str | None:
    """Trigger an agent job via the API (fire-and-forget session creation).

    Instead of spawning a subprocess directly, this sends a request to the daemon
    to create a session with job metadata. The daemon handles execution.
    """
    message = _build_agent_job_message(job_name, config)
    if not message:
        return None

    agent = str(config.agent or "claude")
    thinking_mode = str(config.thinking_mode or "fast")

    # Job sessions are always created on the local computer where the runner is active
    computer = global_config.computer.name
    # Project root is assumed to be current repo root
    project_path = str(_REPO_ROOT)

    async def _trigger() -> str | None:
        client = TelecAPIClient()
        await client.connect()
        try:
            response = await client.create_session(
                computer=computer,
                project_path=project_path,
                agent=agent,
                thinking_mode=thinking_mode,
                title=f"Job: {job_name}",
                message=message,
                metadata={"system_role": ROLE_JOB_RUNNER, "job": job_name, "job_type": config.type or "agent"},
            )
            return response.session_id
        except Exception as e:
            logger.error("agent job API trigger failed", name=job_name, error=str(e))
            return None
        finally:
            await client.close()

    try:
        return asyncio.run(_trigger())
    except Exception as e:
        logger.error("agent job trigger crashed", name=job_name, error=str(e))
        return None


def _run_log_bug_hunter_orchestrated() -> bool:
    """Dispatch ``log_bug_hunter`` across all subscribed registered projects.

    Unlike other agent jobs — which spawn a single session rooted at the
    local repository — ``log_bug_hunter`` is cross-project by design. This
    helper walks :class:`ProjectCatalogService`, filters projects whose
    ``teleclaude.yml:jobs`` subscribes to ``log_bug_hunter``, and runs a
    per-project :class:`LogBugHunterService` via :class:`ProjectJobOrchestrator`.
    Returns ``True`` when the iteration completes without an uncaught
    exception. Per-project failures are isolated and persisted by the
    service's own state; they do not fail the whole job.
    """
    # Imports are local so that cron_runner startup stays lean and importing
    # this module does not pull in the daemon API client at module load time.
    catalog = get_project_catalog_service()
    catalog.refresh()
    computer = global_config.computer.name

    async def _orchestrate() -> bool:
        client = TelecAPIClient()
        await client.connect()
        try:

            async def _create_session(cmd: CreateSessionCommand) -> dict[str, str]:
                intent = cmd.launch_intent
                if intent is None:
                    raise ValueError("log_bug_hunter dispatch requires a launch_intent")
                response = await client.create_session(
                    computer=computer,
                    project_path=cmd.project_path,
                    agent=intent.agent or "codex",
                    thinking_mode=intent.thinking_mode or "fast",
                    message=intent.message or "",
                    metadata={
                        "system_role": cmd.system_role or ROLE_JOB_RUNNER,
                        "job": cmd.job or LOG_BUG_HUNTER_JOB,
                        "job_type": "agent",
                    },
                )
                return {"session_id": response.session_id}

            async def _list_active_sessions() -> list[Session]:
                # The service only reads ``session.job`` — ``SessionDTO`` carries
                # the same attribute, so we cast at this narrow boundary instead
                # of round-tripping through the core model.
                dtos = await client.list_sessions(computer=computer)
                return cast(list[Session], dtos)

            async def _run_for_project(node: ProjectNode) -> bool:
                service = LogBugHunterService(
                    create_session=_create_session,
                    list_active_sessions=_list_active_sessions,
                    project_root=node.root,
                    project_slug=node.slug,
                    state_path=LOG_BUG_HUNTER_STATE_DIR / f"{node.slug}.json",
                )
                return await service.maybe_dispatch()

            orchestrator = ProjectJobOrchestrator(
                catalog=catalog,
                job_slug=LOG_BUG_HUNTER_JOB,
                run_for_project=_run_for_project,
            )
            results = await orchestrator.run_once()
            logger.info(
                "log_bug_hunter orchestration complete",
                project_count=len(results),
                dispatched=[slug for slug, dispatched in results if dispatched],
            )
            return True
        finally:
            await client.close()

    try:
        return asyncio.run(_orchestrate())
    except Exception as exc:
        logger.error("log_bug_hunter orchestration crashed", error=str(exc))
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
    if root is None:
        root = TELECLAUDE_HOME

    people_dir = root / "people"
    if not people_dir.is_dir():
        return False

    job_state = state.get_job(job_name)

    for person_dir in sorted(people_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        cfg_path = person_dir / ConfigFileName.OVERLAY
        if not cfg_path.exists():
            continue
        try:
            person_cfg = load_person_config(cfg_path)
        except Exception:
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


def _resolve_script_path(script: str, root: Path | None = None) -> Path:
    if root is None:
        root = _REPO_ROOT
    path = Path(script)
    if not path.is_absolute():
        path = root / path
    return path


def _script_to_module_name(script: str, root: Path | None = None) -> str | None:
    """Resolve a configured job script to its importable module name."""
    if root is None:
        root = _REPO_ROOT
    script_path = _resolve_script_path(script, root=root)
    try:
        relative = script_path.with_suffix("").relative_to(root)
    except ValueError:
        return None
    return ".".join(relative.parts)


def discover_jobs(jobs_dir: Path | None = None) -> list[ScriptJob]:
    """Discover configured standalone script jobs from teleclaude.yml."""
    if jobs_dir is None:
        config_path = _REPO_ROOT / ConfigFileName.OVERLAY
    else:
        config_path = jobs_dir.parent / ConfigFileName.OVERLAY
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
        module_name = _script_to_module_name(script, root=config_root)
        if module_name is None:
            logger.error("configured job script is outside project root", name=name, script=str(script_path))
            continue
        jobs.append(ScriptJob(name=name, script=script, module_name=module_name))
        logger.debug("discovered job", name=name, script=script)

    return jobs


def _load_script_job(job: ScriptJob) -> Job:
    """Load the module-level JOB object for a configured script job."""
    module = importlib.import_module(job.module_name)
    discovered = getattr(module, "JOB", None)
    if not isinstance(discovered, Job):
        raise TypeError(f"{job.module_name}.JOB must be a jobs.base.Job")
    return discovered


def _run_script_job(job: ScriptJob, timeout_s: int | None = None) -> tuple[JobResult, bool]:
    """Run a script job in-process and report whether it timed out."""
    timeout = timeout_s or _DEFAULT_JOB_TIMEOUT_S
    result_queue: Queue[JobResult] = Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_queue.put(_load_script_job(job).run())
        except Exception as exc:
            logger.exception("job error", name=job.name, error=str(exc))
            result_queue.put(JobResult(success=False, message=str(exc), errors=[str(exc)]))

    thread = threading.Thread(target=_worker, name=f"teleclaude-job-{job.name}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return JobResult(success=False, message=f"{job.name} timed out after {timeout}s"), True
    return result_queue.get(), False


def _dispatch_agent_job(job_name: str, schedule_config: JobScheduleConfig) -> str | None:
    """Dispatch a generic agent job as a single session rooted at the local repo."""
    return _run_agent_job(job_name, schedule_config)


def _pending_emission_for_result(
    job_name: str,
    result: JobResult,
    *,
    run_started_at: datetime,
) -> PendingEmission:
    status = JobRunStatus.SUCCESS if result.success else JobRunStatus.FAILED
    event_type = JobRunEventType.SUCCEEDED if result.success else JobRunEventType.FAILED
    return PendingEmission(
        idempotency_key=f"{job_name}:{run_started_at.isoformat()}",
        event_type=event_type.value,
        job_name=job_name,
        status=status,
        message=result.message,
        items=result.items_processed,
        actionable=not result.success,
    )


def _pending_emission_for_stall(job_name: str, *, run_started_at: datetime, message: str) -> PendingEmission:
    return PendingEmission(
        idempotency_key=f"{job_name}:{run_started_at.isoformat()}",
        event_type=JobRunEventType.STALLED.value,
        job_name=job_name,
        status=JobRunStatus.STALLED,
        message=message,
        items=0,
        actionable=True,
    )


def _close_run_with_emission(
    state: CronState,
    job_name: str,
    result: JobResult,
    *,
    run_started_at: datetime,
) -> None:
    state.close_run(job_name, result, persist=False)
    state.add_pending_emission(
        _pending_emission_for_result(job_name, result, run_started_at=run_started_at), persist=False
    )
    state.save()


def _mark_stalled_with_emission(
    state: CronState,
    job_name: str,
    *,
    run_started_at: datetime,
    message: str,
) -> None:
    state.mark_stalled(job_name, message, persist=False)
    state.add_pending_emission(
        _pending_emission_for_stall(job_name, run_started_at=run_started_at, message=message),
        persist=False,
    )
    state.save()


def _event_level_for_status(status: JobRunStatus) -> EventLevel:
    if status is JobRunStatus.SUCCESS:
        return EventLevel.WORKFLOW
    return EventLevel.OPERATIONAL


def _envelope_for_pending_emission(emission: PendingEmission) -> EventEnvelope:
    human_action = None
    if emission.status in (JobRunStatus.FAILED, JobRunStatus.STALLED):
        human_action = HumanActionIntent(
            topic="Recurring job needs attention",
            summary=emission.message,
            action="Investigate the job",
        )
    return EventEnvelope(
        event=emission.event_type,
        source="cron.runner",
        level=_event_level_for_status(emission.status),
        domain="jobs",
        description=emission.message,
        visibility=EventVisibility.CLUSTER,
        entity=emission.job_name,
        idempotency_key=emission.idempotency_key,
        human_action=human_action,
        payload={
            "job_name": emission.job_name,
            "status": emission.status.value,
            "message": emission.message,
            "items": emission.items,
            "actionable": emission.actionable,
        },
    )


def _drain_pending_emissions(state: CronState) -> None:
    pending = state.iter_pending_emissions()
    if not pending:
        return
    producer = ensure_event_producer()

    async def _drain() -> list[str]:
        published: list[str] = []
        for emission in pending:
            await producer.emit(_envelope_for_pending_emission(emission))
            published.append(emission.idempotency_key)
        return published

    published_keys = asyncio.run(_drain())
    for key in published_keys:
        state.remove_pending_emission(key, persist=False)
    state.save()


def _run_timeout(schedule_config: JobScheduleConfig | None) -> timedelta:
    timeout = schedule_config.timeout if schedule_config and schedule_config.timeout else _DEFAULT_JOB_TIMEOUT_S
    return timedelta(seconds=timeout)


def _load_reported_result(path: Path) -> JobResult | None:
    if not path.exists():
        return None
    try:
        return JobResult.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("invalid job result record", path=str(path))
        return None


def _find_reported_result(job_name: str, run_started_at: datetime, jobs_dir: Path) -> JobResult | None:
    runs_dir = jobs_dir / job_name / "runs"
    if not runs_dir.is_dir():
        return None
    for path in sorted(runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if mtime < run_started_at:
            continue
        result = _load_reported_result(path)
        if result is not None:
            return result
    return None


def _close_reported_agent_runs(
    state: CronState,
    schedules: dict[str, JobScheduleConfig],
    *,
    jobs_dir: Path = JOBS_DIR,
) -> None:
    for job_name, job_state in state.iter_open_runs():
        schedule_config = schedules.get(job_name)
        if not schedule_config or schedule_config.type != "agent" or job_state.run_started_at is None:
            continue
        result = _find_reported_result(job_name, job_state.run_started_at, jobs_dir)
        if result is None:
            continue
        _close_run_with_emission(state, job_name, result, run_started_at=job_state.run_started_at)


def _mark_stalled_runs(
    state: CronState,
    schedules: dict[str, JobScheduleConfig],
    *,
    now: datetime,
) -> None:
    for job_name, job_state in state.iter_open_runs():
        if job_state.run_started_at is None:
            continue
        timeout = _run_timeout(schedules.get(job_name))
        if now - job_state.run_started_at <= timeout:
            continue
        _mark_stalled_with_emission(
            state,
            job_name,
            run_started_at=job_state.run_started_at,
            message=f"{job_name} stalled after {timeout.total_seconds():.0f}s",
        )


def _job_is_due(
    job_name: str,
    job_state_last_run: datetime | None,
    job_state_first_seen_at: datetime | None,
    schedule_config: JobScheduleConfig | None,
    state: CronState,
    now: datetime,
    *,
    force: bool,
    root: Path | None,
) -> bool:
    if force:
        return True
    if schedule_config is None:
        return False
    if schedule_config.category == "subscription":
        return _should_run_subscription_job(job_name, state, now, root=root)
    if job_state_last_run is None:
        return _is_first_run_due(schedule_config, job_state_first_seen_at, now)
    return _is_due(schedule_config, job_state_last_run, now)


def _run_due_agent_job(
    state: CronState,
    job_name: str,
    schedule_config: JobScheduleConfig,
) -> bool:
    run_started_at = datetime.now(UTC)
    if job_name == LOG_BUG_HUNTER_JOB:
        state.open_run(job_name, started_at=run_started_at)
        success = _run_log_bug_hunter_orchestrated()
        result = JobResult(success=success, message=f"{job_name} completed" if success else f"{job_name} failed")
        _close_run_with_emission(state, job_name, result, run_started_at=run_started_at)
        return success

    session_id = _dispatch_agent_job(job_name, schedule_config)
    if session_id:
        state.open_run(job_name, started_at=run_started_at, session_id=session_id)
        return True
    result = JobResult(success=False, message="agent session spawn failed")
    _close_run_with_emission(state, job_name, result, run_started_at=run_started_at)
    return False


def _run_due_script_job(
    state: CronState,
    job_name: str,
    script_job: ScriptJob,
    schedule_config: JobScheduleConfig | None,
) -> tuple[bool, bool]:
    try:
        run_started_at = datetime.now(UTC)
        state.open_run(job_name, started_at=run_started_at)
        result, timed_out = _run_script_job(script_job, timeout_s=schedule_config.timeout if schedule_config else None)
        _close_run_with_emission(state, job_name, result, run_started_at=run_started_at)
        if result.success:
            logger.info("job completed", name=job_name, message=result.message, items=result.items_processed)
        else:
            logger.error("job failed", name=job_name, message=result.message, errors=result.errors)
        return result.success, timed_out
    except Exception as e:
        run_started_at = state.get_job(job_name).run_started_at or datetime.now(UTC)
        _close_run_with_emission(
            state,
            job_name,
            JobResult(success=False, message=str(e), errors=[str(e)]),
            run_started_at=run_started_at,
        )
        logger.exception("job error", name=job_name, error=str(e))
        return False, False


def _run_pre_dispatch_sweeps(
    state: CronState,
    schedules: dict[str, JobScheduleConfig],
    now: datetime,
) -> None:
    _close_reported_agent_runs(state, schedules, jobs_dir=JOBS_DIR)
    _mark_stalled_runs(state, schedules, now=now)
    _drain_pending_emissions(state)


def run_due_jobs(
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

    Each pass closes reported/stalled runs, drains queued event emissions, and
    opens new due runs without treating dispatch as success.
    """
    if not _acquire_pidlock():
        logger.info("another cron runner is active, skipping")
        return {}

    state = CronState.load()
    script_jobs = discover_jobs()
    schedules = _load_job_schedules()
    now = datetime.now(UTC)
    results: dict[str, bool] = {}

    if not dry_run:
        try:
            _run_pre_dispatch_sweeps(state, schedules, now)
        except Exception as exc:
            logger.error("job outcome emission drain failed", error=str(exc))

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

        if job_state.last_status is JobRunStatus.RUNNING:
            logger.info("job already has an open run, skipping dispatch", name=job_name)
            continue

        if state.has_unnotified_actionable(job_name):
            logger.info("job has an actionable pending outcome, skipping dispatch", name=job_name)
            continue

        if not _job_is_due(
            job_name,
            job_state.last_run,
            job_state.first_seen_at,
            schedule_config,
            state,
            now,
            force=force,
            root=root,
        ):
            logger.debug("job not due", name=job_name, last_run=job_state.last_run)
            continue

        schedule_name = (schedule_config.schedule or "?") if schedule_config else "forced"
        logger.info("job due", name=job_name, schedule=schedule_name, type="agent" if is_agent_job else "python")

        if dry_run:
            results[job_name] = True
            continue

        if is_agent_job and schedule_config is not None:
            results[job_name] = _run_due_agent_job(state, job_name, schedule_config)
            continue

        script_job = next((j for j in script_jobs if j.name == job_name), None)
        if not script_job:
            logger.error("script job not found", name=job_name)
            results[job_name] = False
            continue

        success, timed_out = _run_due_script_job(state, job_name, script_job, schedule_config)
        results[job_name] = success
        if timed_out:
            return results

    if not dry_run:
        try:
            _drain_pending_emissions(state)
        except Exception as exc:
            logger.error("job outcome emission drain failed", error=str(exc))

    return results
