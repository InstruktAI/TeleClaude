"""Cron state management - tracks last run times per job."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, NotRequired, TypedDict, cast

from jobs.base import JobResult
from teleclaude.cron.result_store import job_result_transaction
from teleclaude.cron_status import JobRunStatus as JobRunStatus
from teleclaude.events.renames import current_type_name
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import CRON_STATE_PATH

_JOB_KEY_SEPARATOR = ":"
# How long a closed run's outcome stays readable by its identity. It is far longer than the interval at which
# the job-run operation reads run state: a live operation reads a run within one interval of its closing, and a
# daemon restart stales the operation, so no operation acknowledges an outcome and the runner stays the only writer.
CLOSED_RUN_RETENTION: Final = timedelta(hours=24)
# The single closed-run slot a job entry held before outcomes were kept per run.
_SLOT_STARTED_AT: Final = "closed_run_started_at"
_SLOT_STATUS: Final = "closed_run_status"
_SLOT_ERROR: Final = "closed_run_error"
# The stored keys the closed-run outcomes and their migration name; each is a field of `JobStateDict` or `ClosedRunDict`.
_CLOSED_RUNS: Final = "closed_runs"
_LAST_RUN: Final = "last_run"
_OUTCOME_STATUS: Final = "status"
_OUTCOME_ERROR: Final = "error"
_OUTCOME_CLOSED_AT: Final = "closed_at"


class ClosedRunDict(TypedDict):
    """Serialized outcome of one closed run."""

    status: str
    error: str | None
    closed_at: str


class JobStateDict(TypedDict, total=False):
    """Serialized job state."""

    first_seen_at: str | None
    last_run: str | None
    last_status: str
    last_error: str | None
    run_started_at: str | None
    run_session_id: str | None
    closed_runs: dict[str, ClosedRunDict]


class PendingEmissionDict(TypedDict):
    """Serialized queued event emission."""

    idempotency_key: str
    event_type: str
    job_name: str
    status: str
    message: str
    items: int
    actionable: bool
    run_started_at: NotRequired[str]


class CronStateDict(TypedDict):
    """Serialized cron state."""

    jobs: dict[str, JobStateDict]
    pending_emissions: dict[str, PendingEmissionDict]
    legacy_jobs: dict[str, JobStateDict]
    legacy_pending_emissions: dict[str, PendingEmissionDict]


@dataclass(frozen=True)
class PendingEmission:
    """Event payload queued until the event producer confirms publication."""

    idempotency_key: str
    event_type: str
    job_name: str
    status: JobRunStatus
    message: str
    items: int
    actionable: bool
    run_started_at: str

    def to_dict(self) -> PendingEmissionDict:
        """Serialize pending emission to a dictionary."""
        return {
            "idempotency_key": self.idempotency_key,
            "event_type": self.event_type,
            "job_name": self.job_name,
            "status": self.status.value,
            "message": self.message,
            "items": self.items,
            "actionable": self.actionable,
            "run_started_at": self.run_started_at,
        }

    @classmethod
    def from_dict(cls, data: PendingEmissionDict) -> PendingEmission:
        """Deserialize a pending emission, bringing one stored before the platform renames forward.

        The stored type name is read through the platform rename table, and an emission
        stored without its run start takes it from the idempotency key, which is
        ``<job name>:<run start>``.
        """
        job_name = str(data["job_name"])
        idempotency_key = str(data["idempotency_key"])
        return cls(
            idempotency_key=idempotency_key,
            event_type=current_type_name(str(data["event_type"])),
            job_name=job_name,
            status=_parse_status(str(data["status"])),
            message=str(data["message"]),
            items=int(data["items"]),
            actionable=bool(data["actionable"]),
            run_started_at=data.get("run_started_at") or idempotency_key.removeprefix(job_name + _JOB_KEY_SEPARATOR),
        )


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _parse_status(raw: str | None) -> JobRunStatus:
    if raw is None:
        return JobRunStatus.NEVER
    try:
        return JobRunStatus(raw)
    except ValueError:
        return JobRunStatus.NEVER


@dataclass(frozen=True)
class ClosedRun:
    """How one run of a job ended, and when."""

    status: JobRunStatus
    error: str | None
    closed_at: datetime

    def to_dict(self) -> ClosedRunDict:
        """Serialize the closed run to a dictionary."""
        return {
            _OUTCOME_STATUS: self.status.value,
            _OUTCOME_ERROR: self.error,
            _OUTCOME_CLOSED_AT: self.closed_at.isoformat(),
        }


def _parse_closed_runs(raw: dict[str, ClosedRunDict] | None) -> dict[datetime, ClosedRun]:
    """The stored outcomes keyed by the run's start; an entry that does not parse is not an outcome."""
    closed: dict[datetime, ClosedRun] = {}
    for started_raw, outcome in (raw or {}).items():
        started_at = _parse_datetime(started_raw)
        closed_at = _parse_datetime(outcome.get(_OUTCOME_CLOSED_AT))
        if started_at is None or closed_at is None:
            continue
        closed[started_at] = ClosedRun(
            status=_parse_status(outcome.get(_OUTCOME_STATUS)), error=outcome.get(_OUTCOME_ERROR), closed_at=closed_at
        )
    return closed


def _keyed_closed_runs(job_data: JobStateDict) -> tuple[JobStateDict, bool]:
    """The stored job entry in the current shape, and whether it had to change.

    An entry that still holds the single closed-run slot has it moved into the keyed outcomes, closed when
    the entry's last run completed.
    """
    stored = cast(dict[str, object], job_data)  # guard: loose-dict - a stored entry before it is migrated
    if _SLOT_STARTED_AT not in stored and _SLOT_STATUS not in stored and _SLOT_ERROR not in stored:
        return job_data, _CLOSED_RUNS not in job_data
    current = {key: value for key, value in stored.items() if key not in (_SLOT_STARTED_AT, _SLOT_STATUS, _SLOT_ERROR)}
    started_raw = stored.get(_SLOT_STARTED_AT)
    status_raw = stored.get(_SLOT_STATUS)
    if isinstance(started_raw, str) and isinstance(status_raw, str):
        error = stored.get(_SLOT_ERROR)
        closed_at = job_data.get(_LAST_RUN) or started_raw
        keyed = dict(job_data.get(_CLOSED_RUNS) or {})
        keyed[started_raw] = {
            _OUTCOME_STATUS: status_raw,
            _OUTCOME_ERROR: error if isinstance(error, str) else None,
            _OUTCOME_CLOSED_AT: closed_at,
        }
        current[_CLOSED_RUNS] = keyed
    return cast(JobStateDict, current), True


@dataclass
class JobState:
    """State for a single job."""

    first_seen_at: datetime | None = None
    last_run: datetime | None = None
    last_status: JobRunStatus = JobRunStatus.NEVER
    last_error: str | None = None
    run_started_at: datetime | None = None
    run_session_id: str | None = None
    # Each recently closed run's outcome by the run's start, kept apart from `last_status` so a successor
    # opening or closing does not erase how an earlier run ended.
    closed_runs: dict[datetime, ClosedRun] = field(default_factory=dict)

    def to_dict(self) -> JobStateDict:
        """Serialize job state to a dictionary."""
        return {
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_status": self.last_status.value,
            "last_error": self.last_error,
            "run_started_at": self.run_started_at.isoformat() if self.run_started_at else None,
            "run_session_id": self.run_session_id,
            _CLOSED_RUNS: {started_at.isoformat(): closed.to_dict() for started_at, closed in self.closed_runs.items()},
        }

    @classmethod
    def from_dict(cls, data: JobStateDict) -> JobState:
        """Deserialize job state from a dictionary."""
        return cls(
            first_seen_at=_parse_datetime(data.get("first_seen_at")),
            last_run=_parse_datetime(data.get("last_run")),
            last_status=_parse_status(data.get("last_status")),
            last_error=data.get("last_error"),
            run_started_at=_parse_datetime(data.get("run_started_at")),
            run_session_id=data.get("run_session_id"),
            closed_runs=_parse_closed_runs(data.get(_CLOSED_RUNS)),
        )


@dataclass
class CronState:
    """Manages cron state persistence."""

    path: Path
    jobs: dict[str, JobState] = field(default_factory=dict)
    pending_emissions: dict[str, PendingEmission] = field(default_factory=dict)
    legacy_jobs: dict[str, JobState] = field(default_factory=dict)
    legacy_pending_emissions: dict[str, PendingEmission] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        path: Path | None = None,
        *,
        legacy_project_slug: str | None = None,
        aggregate_job_keys: frozenset[str] = frozenset(),
        persist_migrations: bool = True,
    ) -> CronState:
        """Load state from disk or create new."""
        if path is None:
            path = CRON_STATE_PATH
        state = cls(path=path)
        needs_migration = False
        if path.exists():
            try:
                data_obj = json.loads(path.read_text(encoding="utf-8"))
                data = (  # guard: loose-dict - YAML state file — dynamic shape
                    cast(dict[str, object], data_obj) if isinstance(data_obj, dict) else {}
                )
                jobs_obj = data.get("jobs", {})
                jobs = cast(dict[str, JobStateDict], jobs_obj) if isinstance(jobs_obj, dict) else {}
                for job_name, stored_job in jobs.items():
                    job_data, reshaped = _keyed_closed_runs(stored_job)
                    if (
                        reshaped
                        or "run_started_at" not in job_data
                        or "run_session_id" not in job_data
                        or "last_notified" in job_data
                    ):
                        needs_migration = True
                    target = state.legacy_jobs if job_name in aggregate_job_keys else state.jobs
                    migrated_name = _migrate_job_key(job_name, legacy_project_slug)
                    if migrated_name != job_name:
                        needs_migration = True
                    target[migrated_name] = JobState.from_dict(job_data)
                pending_obj = data.get("pending_emissions", {})
                if not isinstance(pending_obj, dict):
                    needs_migration = True
                    pending_obj = {}
                pending = cast(dict[str, PendingEmissionDict], pending_obj)
                for key, emission_data in pending.items():
                    try:
                        emission = PendingEmission.from_dict(emission_data)
                        if emission.job_name in aggregate_job_keys:
                            state.legacy_pending_emissions[key] = emission
                            needs_migration = True
                        else:
                            migrated_name = _migrate_job_key(emission.job_name, legacy_project_slug)
                            if migrated_name != emission.job_name:
                                emission = replace(emission, job_name=migrated_name)
                                needs_migration = True
                            state.pending_emissions[key] = emission
                    except (KeyError, TypeError, ValueError):
                        needs_migration = True
                if "pending_emissions" not in data:
                    needs_migration = True
                legacy_jobs_obj = data.get("legacy_jobs", {})
                if isinstance(legacy_jobs_obj, dict):
                    for job_name, stored_job in cast(dict[str, JobStateDict], legacy_jobs_obj).items():
                        legacy_data, reshaped = _keyed_closed_runs(stored_job)
                        needs_migration = needs_migration or reshaped
                        state.legacy_jobs[job_name] = JobState.from_dict(legacy_data)
                legacy_pending_obj = data.get("legacy_pending_emissions", {})
                if isinstance(legacy_pending_obj, dict):
                    for key, emission_data in cast(dict[str, PendingEmissionDict], legacy_pending_obj).items():
                        state.legacy_pending_emissions[key] = PendingEmission.from_dict(emission_data)
            except (json.JSONDecodeError, KeyError):
                pass
        if needs_migration and persist_migrations:
            state.save()
        return state

    def save(self) -> None:
        """Persist state to disk."""
        data: CronStateDict = {
            "jobs": {name: job.to_dict() for name, job in self.jobs.items()},
            "pending_emissions": {key: emission.to_dict() for key, emission in self.pending_emissions.items()},
            "legacy_jobs": {name: job.to_dict() for name, job in self.legacy_jobs.items()},
            "legacy_pending_emissions": {
                key: emission.to_dict() for key, emission in self.legacy_pending_emissions.items()
            },
        }
        with file_transaction(self.path) as transaction:
            transaction.replace_text(json.dumps(data, indent=2))

    def get_job(self, name: str) -> JobState:
        """Get or create job state."""
        if name not in self.jobs:
            self.jobs[name] = JobState()
        return self.jobs[name]

    def ensure_first_seen(self, name: str, seen_at: datetime | None = None) -> JobState:
        """Persist a first-seen timestamp for jobs discovered by the runner."""
        job = self.get_job(name)
        if job.first_seen_at is None and job.last_run is None:
            job.first_seen_at = seen_at or datetime.now(UTC)
            self.save()
        return job

    def open_run(
        self,
        name: str,
        *,
        started_at: datetime,
        session_id: str | None = None,
        persist: bool = True,
    ) -> JobState:
        """Open a run for a job at dispatch time."""
        with _job_lifecycle_lock(name, persist=persist):
            job = self.get_job(name)
            job.run_started_at = started_at
            job.run_session_id = session_id
            job.last_status = JobRunStatus.RUNNING
            job.last_error = None
            if persist:
                self.save()
        return job

    def close_run(
        self,
        name: str,
        result: JobResult,
        *,
        closed_at: datetime | None = None,
        persist: bool = True,
    ) -> JobState:
        """Close an open run with a real job result."""
        with _job_lifecycle_lock(name, persist=persist):
            job = self.get_job(name)
            job.last_run = closed_at or datetime.now(UTC)
            job.last_status = JobRunStatus.SUCCESS if result.success else JobRunStatus.FAILED
            job.last_error = None if result.success else result.message
            _record_closed_run(job, job.last_run)
            job.run_started_at = None
            job.run_session_id = None
            if persist:
                self.save()
        return job

    def mark_stalled(
        self,
        name: str,
        error: str,
        *,
        stalled_at: datetime | None = None,
        persist: bool = True,
    ) -> JobState:
        """Mark an open run as stalled."""
        with _job_lifecycle_lock(name, persist=persist):
            job = self.get_job(name)
            job.last_run = stalled_at or datetime.now(UTC)
            job.last_status = JobRunStatus.STALLED
            job.last_error = error
            _record_closed_run(job, job.last_run)
            job.run_started_at = None
            job.run_session_id = None
            if persist:
                self.save()
        return job

    def add_pending_emission(self, emission: PendingEmission, *, persist: bool = True) -> None:
        """Queue a job outcome event until publication succeeds."""
        self.pending_emissions[emission.idempotency_key] = emission
        if persist:
            self.save()

    def remove_pending_emission(self, key: str, *, persist: bool = True) -> None:
        """Remove a queued outcome event after confirmed publication."""
        self.pending_emissions.pop(key, None)
        if persist:
            self.save()

    def iter_pending_emissions(self) -> list[PendingEmission]:
        """Return queued emissions in deterministic order."""
        return [self.pending_emissions[key] for key in sorted(self.pending_emissions)]

    def has_unnotified_actionable(self, name: str) -> bool:
        """Return whether a job has an actionable queued outcome."""
        return any(emission.job_name == name and emission.actionable for emission in self.pending_emissions.values())

    def iter_open_runs(self) -> list[tuple[str, JobState]]:
        """Return jobs with a run currently open."""
        return [
            (name, job)
            for name, job in sorted(self.jobs.items())
            if job.last_status is JobRunStatus.RUNNING and job.run_started_at is not None
        ]


def _record_closed_run(job: JobState, closed_at: datetime) -> None:
    """Keep how the open run ended under its start, and drop outcomes older than the retention window."""
    if job.run_started_at is not None:
        job.closed_runs[job.run_started_at] = ClosedRun(job.last_status, job.last_error, closed_at)
    expiry = closed_at - CLOSED_RUN_RETENTION
    job.closed_runs = {
        started_at: closed for started_at, closed in job.closed_runs.items() if closed.closed_at > expiry
    }


class RunLookup(StrEnum):
    """Whether a run is still open, has closed, or has neither an open run nor a retained outcome."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RunState:
    """The state of one run of a job: whether it is open, and when closed how it ended."""

    lookup: RunLookup
    status: JobRunStatus | None = None
    error: str | None = None


def read_run_state(job_key: str, run_started_at: datetime) -> RunState:
    """Whether the run a job opened at `run_started_at` is open or closed, and how a closed run ended.

    Reads the persisted state without writing it: the runner is its only writer. A closed run's outcome is
    found by its start, so a successor opening or closing never replaces it; a run is unknown once it is
    neither the open run nor within the closed-run retention window.
    """
    job = CronState.load(persist_migrations=False).jobs.get(job_key)
    if job is None:
        return RunState(RunLookup.UNKNOWN)
    if job.last_status is JobRunStatus.RUNNING and job.run_started_at == run_started_at:
        return RunState(RunLookup.OPEN)
    closed = job.closed_runs.get(run_started_at)
    if closed is not None:
        return RunState(RunLookup.CLOSED, status=closed.status, error=closed.error)
    return RunState(RunLookup.UNKNOWN)


def compose_job_key(project_slug: str, job_identity: str) -> str:
    """Compose the project-qualified identity used to track a scheduled job."""
    return _JOB_KEY_SEPARATOR.join((project_slug, job_identity))


def project_slug_for_job_key(job_key: str) -> str | None:
    """Return the project slug from a qualified job key, or None for a legacy key."""
    parsed = split_job_key(job_key)
    return parsed[0] if parsed is not None else None


def split_job_key(job_key: str) -> tuple[str, str] | None:
    """Return the project slug and job identity from a qualified scheduler key."""
    project_slug, separator, job_identity = job_key.partition(_JOB_KEY_SEPARATOR)
    if not separator or not project_slug or not job_identity:
        return None
    return project_slug, job_identity


@contextmanager
def _job_lifecycle_lock(job_key: str, *, persist: bool) -> Iterator[None]:
    parsed = split_job_key(job_key)
    if not persist or parsed is None:
        yield
        return
    with job_result_transaction(*parsed):
        yield


def _migrate_job_key(job_name: str, legacy_project_slug: str | None) -> str:
    """Qualify a pre-cutover ordinary job with its known runner project."""
    if legacy_project_slug is None or _JOB_KEY_SEPARATOR in job_name:
        return job_name
    return compose_job_key(legacy_project_slug, job_name)
