"""Cron state management - tracks last run times per job."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from jobs.base import JobResult
from teleclaude.cron_status import JobRunStatus as JobRunStatus
from teleclaude.events.renames import current_type_name
from teleclaude.paths import CRON_STATE_PATH

_JOB_KEY_SEPARATOR = ":"


class JobStateDict(TypedDict, total=False):
    """Serialized job state."""

    first_seen_at: str | None
    last_run: str | None
    last_status: str
    last_error: str | None
    run_started_at: str | None
    run_session_id: str | None


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


@dataclass
class JobState:
    """State for a single job."""

    first_seen_at: datetime | None = None
    last_run: datetime | None = None
    last_status: JobRunStatus = JobRunStatus.NEVER
    last_error: str | None = None
    run_started_at: datetime | None = None
    run_session_id: str | None = None

    def to_dict(self) -> JobStateDict:
        """Serialize job state to a dictionary."""
        return {
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_status": self.last_status.value,
            "last_error": self.last_error,
            "run_started_at": self.run_started_at.isoformat() if self.run_started_at else None,
            "run_session_id": self.run_session_id,
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
                for job_name, job_data in jobs.items():
                    if (
                        "run_started_at" not in job_data
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
                    for job_name, job_data in cast(dict[str, JobStateDict], legacy_jobs_obj).items():
                        state.legacy_jobs[job_name] = JobState.from_dict(job_data)
                legacy_pending_obj = data.get("legacy_pending_emissions", {})
                if isinstance(legacy_pending_obj, dict):
                    for key, emission_data in cast(dict[str, PendingEmissionDict], legacy_pending_obj).items():
                        state.legacy_pending_emissions[key] = PendingEmission.from_dict(emission_data)
            except (json.JSONDecodeError, KeyError):
                pass
        if needs_migration:
            state.save()
        return state

    def save(self) -> None:
        """Persist state to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data: CronStateDict = {
            "jobs": {name: job.to_dict() for name, job in self.jobs.items()},
            "pending_emissions": {key: emission.to_dict() for key, emission in self.pending_emissions.items()},
            "legacy_jobs": {name: job.to_dict() for name, job in self.legacy_jobs.items()},
            "legacy_pending_emissions": {
                key: emission.to_dict() for key, emission in self.legacy_pending_emissions.items()
            },
        }
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
        job = self.get_job(name)
        job.last_run = closed_at or datetime.now(UTC)
        job.last_status = JobRunStatus.SUCCESS if result.success else JobRunStatus.FAILED
        job.last_error = None if result.success else result.message
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
        job = self.get_job(name)
        job.last_run = stalled_at or datetime.now(UTC)
        job.last_status = JobRunStatus.STALLED
        job.last_error = error
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


def compose_job_key(project_slug: str, job_identity: str) -> str:
    """Compose the project-qualified identity used to track a scheduled job."""
    return _JOB_KEY_SEPARATOR.join((project_slug, job_identity))


def project_slug_for_job_key(job_key: str) -> str | None:
    """Return the project slug from a qualified job key, or None for a legacy key."""
    project_slug, separator, job_identity = job_key.partition(_JOB_KEY_SEPARATOR)
    return project_slug if separator and job_identity else None


def _migrate_job_key(job_name: str, legacy_project_slug: str | None) -> str:
    """Qualify a pre-cutover ordinary job with its known runner project."""
    if legacy_project_slug is None or _JOB_KEY_SEPARATOR in job_name:
        return job_name
    return compose_job_key(legacy_project_slug, job_name)
