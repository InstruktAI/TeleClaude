"""Cron state management - tracks last run times per job."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from typing_extensions import TypedDict


class JobStateDict(TypedDict, total=False):
    """Serialized job state."""

    last_run: str | None
    last_status: str
    last_error: str | None
    last_notified: str | None


class CronStateDict(TypedDict):
    """Serialized cron state."""

    jobs: dict[str, JobStateDict]


@dataclass
class JobState:
    """State for a single job."""

    last_run: datetime | None = None
    last_status: str = "never"  # "success", "failed", "never"
    last_error: str | None = None
    last_notified: datetime | None = None

    def to_dict(self) -> JobStateDict:
        return {
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_notified": self.last_notified.isoformat() if self.last_notified else None,
        }

    @classmethod
    def from_dict(cls, data: JobStateDict) -> JobState:
        last_run = None
        last_run_str = data.get("last_run")
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
            except (ValueError, TypeError):
                pass
        last_notified = None
        last_notified_str = data.get("last_notified")
        if last_notified_str:
            try:
                last_notified = datetime.fromisoformat(last_notified_str)
            except (ValueError, TypeError):
                pass
        return cls(
            last_run=last_run,
            last_status=data.get("last_status", "never"),
            last_error=data.get("last_error"),
            last_notified=last_notified,
        )


@dataclass
class CronState:
    """Manages cron state persistence."""

    path: Path
    jobs: dict[str, JobState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> CronState:
        """Load state from disk or create new."""
        if path is None:
            path = Path.home() / ".teleclaude" / "cron_state.json"
        state = cls(path=path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for job_name, job_data in data.get("jobs", {}).items():
                    state.jobs[job_name] = JobState.from_dict(job_data)
            except (json.JSONDecodeError, KeyError):
                pass
        return state

    def save(self) -> None:
        """Persist state to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"jobs": {name: job.to_dict() for name, job in self.jobs.items()}}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_job(self, name: str) -> JobState:
        """Get or create job state."""
        if name not in self.jobs:
            self.jobs[name] = JobState()
        return self.jobs[name]

    def mark_success(self, name: str) -> None:
        """Mark job as successfully completed."""
        job = self.get_job(name)
        job.last_run = datetime.now(timezone.utc)
        job.last_status = "success"
        job.last_error = None
        self.save()

    def mark_failed(self, name: str, error: str) -> None:
        """Mark job as failed."""
        job = self.get_job(name)
        job.last_run = datetime.now(timezone.utc)
        job.last_status = "failed"
        job.last_error = error
        self.save()

    def mark_notified(self, name: str, timestamp: datetime) -> None:
        """Record that notifications were sent for a job up to the given timestamp."""
        job = self.get_job(name)
        job.last_notified = timestamp
        self.save()
