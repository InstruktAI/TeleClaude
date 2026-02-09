"""Base job class and result type.

Job modules implement the work to be done. Scheduling is managed externally
via teleclaude.yml — jobs are invoked by the runner when their configured
schedule is due. Jobs are schedule-ignorant: they define a name and a run()
method, nothing more.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class JobResult:
    """Result of a job execution."""

    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None


class Job(ABC):
    """Base class for scheduled jobs.

    Subclasses provide a unique name and implement run(). Scheduling
    configuration lives in teleclaude.yml, not in the job itself.
    """

    name: str

    @abstractmethod
    def run(self) -> JobResult:
        """Execute the job. Returns result with success/failure info."""
        ...

    def required_subscriber_fields(self) -> list[str]:
        """Return required subscriber-level config fields for this job.

        Optional contract for jobs that depend on per-subscriber config data.
        Field syntax is dot-path style (for example: ``subscriptions.youtube``).
        """
        return []
