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
import importlib.util
import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path
from queue import Queue
from types import ModuleType

from instrukt_ai_logging import get_logger

from jobs.base import Job, JobResult, JobRunContext
from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.config import config as global_config
from teleclaude.config.jobs import EffectiveJob, load_effective_jobs
from teleclaude.config.loader import load_person_config, load_project_config
from teleclaude.config.schema import JobScheduleConfig, JobSubscription, is_agent_job, job_identity
from teleclaude.constants import SlashCommand
from teleclaude.core.models import HumanActionIntent
from teleclaude.cron.state import CronState, JobRunStatus, PendingEmission
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.producer import ensure_event_producer
from teleclaude.events.schemas.jobs import JobRunEventType
from teleclaude.paths import CRON_PID_PATH, JOBS_DIR, TELECLAUDE_HOME, ConfigFileName
from teleclaude.project_root import resolve_project_root
from teleclaude.services.project_catalog import ProjectCatalogService, ProjectNode, get_project_catalog_service

logger = get_logger(__name__)

_NEXT_RUN_JOB_COMMAND = f"/{SlashCommand.NEXT_RUN_JOB.value}"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DYNAMIC_JOB_PACKAGE_PREFIX = "_teleclaude_job"
_LEGACY_AGGREGATE_JOB_KEYS = frozenset({"log-bug-hunter", "software-development/procedure/maintenance/log-bug-hunter"})


class Schedule(Enum):
    """Job schedule frequencies."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


def _load_job_schedules(config_path: Path | None = None) -> list[JobScheduleConfig]:
    """Load job schedule configuration from teleclaude.yml."""
    if config_path is None:
        config_path = _REPO_ROOT / ConfigFileName.OVERLAY

    config = load_project_config(config_path)
    return config.jobs


def load_job_schedules(config_path: Path | None = None) -> list[JobScheduleConfig]:
    """Load job schedule configuration from teleclaude.yml."""
    return _load_job_schedules(config_path)


def load_job_state(catalog: ProjectCatalogService | None = None) -> CronState:
    """Load state with the runner-owned forward migration context."""
    active_catalog = catalog or get_project_catalog_service()
    legacy_project = active_catalog.get_by_root(resolve_project_root(_REPO_ROOT))
    return CronState.load(
        legacy_project_slug=legacy_project.slug if legacy_project is not None else None,
        aggregate_job_keys=_LEGACY_AGGREGATE_JOB_KEYS,
    )


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

    return False


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

    return False


_DEFAULT_JOB_TIMEOUT_S = 1800  # 30 minutes
_PIDFILE = CRON_PID_PATH


@dataclass(frozen=True)
class ScriptJob:
    """Configured standalone script job."""

    name: str
    script: str
    origin: Path


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


def _job_command_args(schedule: JobScheduleConfig) -> str:
    """The one argument the run boundary validates for an agent job: its procedure snippet ID."""
    return str(schedule.job or "").strip()


def _run_agent_job(job_name: str, config: JobScheduleConfig, project_root: Path) -> tuple[str | None, str | None]:
    """Trigger an agent job via the API (fire-and-forget session creation).

    Instead of spawning a subprocess directly, this sends a request to the daemon
    to create a session with job metadata. The daemon handles execution.
    """
    # Job sessions are always created on the local computer where the runner is active
    computer = global_config.computer.name
    project_path = str(project_root)

    async def _trigger() -> tuple[str | None, str | None]:
        client = TelecAPIClient(daemon_credential=True)
        await client.connect()
        try:
            response = await client.run_session(
                computer=computer,
                project_path=project_path,
                command=_NEXT_RUN_JOB_COMMAND,
                args=_job_command_args(config),
            )
            return response.session_id, None
        except APIError as error:
            detail = error.detail or str(error)
            logger.error("agent job API trigger refused", name=job_name, error=detail)
            return None, detail
        except Exception as error:
            detail = str(error)
            logger.error("agent job API trigger crashed", name=job_name, error=detail)
            return None, detail
        finally:
            await client.close()

    try:
        return asyncio.run(_trigger())
    except Exception as error:
        detail = str(error)
        logger.error("agent job trigger crashed", name=job_name, error=detail)
        return None, detail


def _should_run_subscription_job(
    job_identity: str,
    state_key: str,
    state: CronState,
    now: datetime,
    *,
    root: Path | None = None,
) -> bool:
    """Check if any subscriber's schedule makes a subscription job due.

    Iterates person configs for enabled JobSubscription entries matching
    *job_identity* and checks if any subscriber's ``when`` schedule is due.
    """
    if root is None:
        root = TELECLAUDE_HOME

    people_dir = root / "people"
    if not people_dir.is_dir():
        return False

    job_state = state.get_job(state_key)

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
            if sub.job != job_identity or not sub.enabled:
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

    for config in schedules:
        name = job_identity("", config)
        script = str(config.script or "").strip()
        if not script:
            continue
        script_path = _resolve_script_path(script, root=config_root)
        if not script_path.exists():
            logger.error("configured job script not found", name=name, script=str(script_path))
            continue
        if _script_to_module_name(script, root=config_root) is None:
            logger.error("configured job script is outside project root", name=name, script=str(script_path))
            continue
        jobs.append(ScriptJob(name=name, script=script, origin=config_root))
        logger.debug("discovered job", name=name, script=script)

    return jobs


def _load_script_job(job: ScriptJob) -> Job:
    """Load the module-level JOB object for a configured script job."""
    script_path = _resolve_script_path(job.script, root=job.origin)
    module_name, package_paths = _script_module_identity(script_path, job.origin)
    _ensure_origin_packages(package_paths)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load configured job module {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    discovered = getattr(module, "JOB", None)
    if not isinstance(discovered, Job):
        raise TypeError(f"{module_name}.JOB must be a jobs.base.Job")
    return discovered


def _script_module_identity(script_path: Path, origin: Path) -> tuple[str, tuple[tuple[str, Path], ...]]:
    """Name a script module by origin and retain its package-relative imports."""
    relative = script_path.with_suffix("").relative_to(origin)
    root_name = f"{_DYNAMIC_JOB_PACKAGE_PREFIX}_{sha256(str(origin).encode()).hexdigest()[:16]}"
    package_paths: list[tuple[str, Path]] = [(root_name, origin)]
    current_name = root_name
    current_path = origin
    for part in relative.parts[:-1]:
        current_name = f"{current_name}.{part}"
        current_path = current_path / part
        package_paths.append((current_name, current_path))
    return f"{root_name}.{'.'.join(relative.parts)}", tuple(package_paths)


def _ensure_origin_packages(package_paths: tuple[tuple[str, Path], ...]) -> None:
    """Register only origin-scoped package parents required for relative imports."""
    for package_name, package_path in package_paths:
        if package_name in sys.modules:
            continue
        package = ModuleType(package_name)
        package.__path__ = [str(package_path)]
        sys.modules[package_name] = package


def _run_script_job(job: ScriptJob, context: JobRunContext, timeout_s: int | None = None) -> tuple[JobResult, bool]:
    """Run a script job in-process and report whether it timed out."""
    timeout = timeout_s or _DEFAULT_JOB_TIMEOUT_S
    result_queue: Queue[JobResult] = Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_queue.put(_load_script_job(job).run(context))
        except Exception as exc:
            logger.exception("job error", name=job.name, error=str(exc))
            result_queue.put(JobResult(success=False, message=str(exc), errors=[str(exc)]))

    thread = threading.Thread(target=_worker, name=f"teleclaude-job-{job.name}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return JobResult(success=False, message=f"{job.name} timed out after {timeout}s"), True
    return result_queue.get(), False


def _dispatch_agent_job(
    job_name: str, schedule_config: JobScheduleConfig, project_root: Path
) -> tuple[str | None, str | None]:
    """Dispatch one generic agent job in its consuming project."""
    return _run_agent_job(job_name, schedule_config, project_root)


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


def _find_reported_result(
    job_name: str, run_started_at: datetime, session_id: str | None, jobs_dir: Path
) -> JobResult | None:
    runs_dir = jobs_dir / job_name / "runs"
    if not runs_dir.is_dir():
        return None
    for path in sorted(runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if mtime < run_started_at:
            continue
        result = _load_reported_result(path)
        if result is not None and result.session_id == session_id:
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
        if not schedule_config or not is_agent_job(schedule_config) or job_state.run_started_at is None:
            continue
        result = _find_reported_result(job_name, job_state.run_started_at, job_state.run_session_id, jobs_dir)
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
    state_key: str,
    job_identity: str,
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
        return _should_run_subscription_job(job_identity, state_key, state, now, root=root)
    if job_state_last_run is None:
        return _is_first_run_due(schedule_config, job_state_first_seen_at, now)
    return _is_due(schedule_config, job_state_last_run, now)


def _run_due_agent_job(
    state: CronState,
    job_name: str,
    schedule_config: JobScheduleConfig,
    *,
    project_root: Path,
) -> bool:
    run_started_at = datetime.now(UTC)
    session_id, refusal_detail = _dispatch_agent_job(job_name, schedule_config, project_root)
    if session_id:
        state.open_run(job_name, started_at=run_started_at, session_id=session_id)
        return True
    result = JobResult(success=False, message=refusal_detail or "agent session spawn failed")
    _close_run_with_emission(state, job_name, result, run_started_at=run_started_at)
    return False


def _run_due_script_job(
    state: CronState,
    job_name: str,
    script_job: ScriptJob,
    schedule_config: JobScheduleConfig | None,
    project_root: Path,
    project_slug: str,
) -> tuple[bool, bool]:
    try:
        run_started_at = datetime.now(UTC)
        state.open_run(job_name, started_at=run_started_at)
        result, timed_out = _run_script_job(
            script_job,
            JobRunContext(project_root=project_root, project_slug=project_slug),
            timeout_s=schedule_config.timeout if schedule_config else None,
        )
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

    catalog = get_project_catalog_service()
    catalog.refresh()
    state = load_job_state(catalog)
    project_jobs: list[tuple[ProjectNode, EffectiveJob]] = []
    schedules: dict[str, JobScheduleConfig] = {}
    for project in catalog.list_projects():
        try:
            effective = load_effective_jobs(project.root)
        except (OSError, ValueError) as exc:
            logger.error("effective job load failed", project=project.slug, error=str(exc))
            continue
        for job in effective:
            job_key = f"{project.slug}:{job.identity}"
            project_jobs.append((project, job))
            schedules[job_key] = job.declaration
    now = datetime.now(UTC)
    results: dict[str, bool] = {}

    if not dry_run:
        try:
            _run_pre_dispatch_sweeps(state, schedules, now)
        except Exception as exc:
            logger.error("job outcome emission drain failed", error=str(exc))

    logger.info("checking jobs", count=len(project_jobs), force=force, dry_run=dry_run)

    for project, effective_job in project_jobs:
        job_name = f"{project.slug}:{effective_job.identity}"
        if job_filter and job_filter not in {job_name, effective_job.identity}:
            continue

        schedule_config = effective_job.declaration
        agent_job = is_agent_job(schedule_config)

        job_state = state.ensure_first_seen(job_name, now)

        if job_state.last_status is JobRunStatus.RUNNING:
            logger.info("job already has an open run, skipping dispatch", name=job_name)
            continue

        if state.has_unnotified_actionable(job_name):
            logger.info("job has an actionable pending outcome, skipping dispatch", name=job_name)
            continue

        if not _job_is_due(
            job_name,
            effective_job.identity,
            job_state.last_run,
            job_state.first_seen_at,
            schedule_config,
            state,
            now,
            force=force,
            root=project.root,
        ):
            logger.debug("job not due", name=job_name, last_run=job_state.last_run)
            continue

        logger.info("job due", name=job_name, type="agent" if agent_job else "python")

        if dry_run:
            results[job_name] = True
            continue

        if agent_job:
            results[job_name] = _run_due_agent_job(
                state,
                job_name,
                schedule_config,
                project_root=project.root,
            )
            continue

        script = schedule_config.script
        if not script:
            logger.error("script job not found", name=job_name)
            results[job_name] = False
            continue
        module_name = _script_to_module_name(script, root=effective_job.origin.root)
        if module_name is None:
            logger.error("configured job script is outside declaration root", name=job_name)
            results[job_name] = False
            continue
        script_job = ScriptJob(name=job_name, script=script, origin=effective_job.origin.root)

        success, timed_out = _run_due_script_job(
            state, job_name, script_job, schedule_config, project.root, project.slug
        )
        results[job_name] = success
        if timed_out:
            return results

    if not dry_run:
        try:
            _drain_pending_emissions(state)
        except Exception as exc:
            logger.error("job outcome emission drain failed", error=str(exc))

    return results
