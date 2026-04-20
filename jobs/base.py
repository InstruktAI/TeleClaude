"""Base job class and result type.

Job modules implement the work to be done. Scheduling is managed externally
via teleclaude.yml — jobs are invoked by the runner when their configured
schedule is due. Jobs are schedule-ignorant: they define a name and a run()
method, nothing more.
"""

from __future__ import annotations

import json
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class JobResult:
    """Result of a job execution."""

    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None

    def to_json(self) -> str:
        """Serialize the result for the cron runner subprocess contract."""
        return json.dumps(asdict(self), ensure_ascii=True)

    @classmethod
    def from_json(cls, raw: str) -> JobResult:
        """Deserialize a result emitted by a standalone job script."""
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Job result payload must be an object")

        success = data.get("success")
        message = data.get("message")
        items_processed = data.get("items_processed", 0)
        errors = data.get("errors")

        if not isinstance(success, bool):
            raise ValueError("Job result success must be a boolean")
        if not isinstance(message, str):
            raise ValueError("Job result message must be a string")
        if not isinstance(items_processed, int):
            raise ValueError("Job result items_processed must be an int")
        if errors is not None:
            if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
                raise ValueError("Job result errors must be a list of strings")

        return cls(
            success=success,
            message=message,
            items_processed=items_processed,
            errors=errors,
        )


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


def run_job_cli(job: Job) -> int:
    """Execute a job as a standalone script and emit a JSON JobResult."""
    try:
        result = job.run()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        result = JobResult(success=False, message=str(exc), errors=[str(exc)])

    print(result.to_json())
    return 0 if result.success else 1
