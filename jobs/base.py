"""Base job class and result type.

Job modules implement the work to be done. Scheduling is managed externally
via teleclaude.yml — jobs are invoked by the runner when their configured
schedule is due. Jobs are schedule-ignorant: they define a run() method,
nothing more.
"""

from __future__ import annotations

import json
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONState = dict[str, JSONValue]
_JOB_RESULT_STATE_FIELD: Final[str] = "state"
_JOB_RESULT_STATE_ERROR: Final[str] = "Job result state must be an object"


@dataclass
class JobResult:
    """Result of a job execution."""

    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None
    session_id: str | None = None
    state: JSONState | None = None

    def to_json(self) -> str:
        """Serialize the result for the cron runner subprocess contract."""
        data = asdict(self)
        if self.state is None:
            data.pop(_JOB_RESULT_STATE_FIELD)
        return json.dumps(data, ensure_ascii=True)

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
        session_id = data.get("session_id")
        state = data.get(_JOB_RESULT_STATE_FIELD)

        if not isinstance(success, bool):
            raise ValueError("Job result success must be a boolean")
        if not isinstance(message, str):
            raise ValueError("Job result message must be a string")
        if not isinstance(items_processed, int):
            raise ValueError("Job result items_processed must be an int")
        if errors is not None:
            if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
                raise ValueError("Job result errors must be a list of strings")
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("Job result session_id must be a string")
        if _JOB_RESULT_STATE_FIELD in data and (
            not isinstance(state, dict) or any(not isinstance(key, str) for key in state)
        ):
            raise ValueError(_JOB_RESULT_STATE_ERROR)

        return cls(
            success=success,
            message=message,
            items_processed=items_processed,
            errors=errors,
            session_id=session_id,
            state=cast(JSONState, state) if state is not None else None,
        )


@dataclass(frozen=True)
class JobRunContext:
    """The consuming project identity supplied by the generic job runner."""

    project_root: Path
    project_slug: str
    state: JSONState | None = None


class Job(ABC):
    """Base class for scheduled jobs.

    Subclasses implement run(). Scheduling and identity live in teleclaude.yml,
    not in the job itself.
    """

    @abstractmethod
    def run(self, context: JobRunContext | None = None) -> JobResult:
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
