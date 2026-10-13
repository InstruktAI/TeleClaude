"""The record a manually dispatched cron runner writes to standard output to say which run it opened.

A dispatch asked for one run of one job in one project. The runner knows, as soon as it has decided,
either the run it opened or why it opened none; it writes that as one typed line so the process that
launched it can follow that run rather than the launch.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

DISPATCH_LINE_PREFIX = "teleclaude-dispatch "


class DispatchRefusal(StrEnum):
    """Why a manual dispatch opened no run."""

    RUNNER_LOCK_HELD = "runner_lock_held"
    RUN_ALREADY_OPEN = "run_already_open"
    UNDELIVERED_OUTCOME = "undelivered_outcome"
    NO_SUCH_JOB = "no_such_job"
    START_FAILED = "start_failed"


class JobDispatchRecord(BaseModel):
    """The run a dispatch opened, or the reason it opened none."""

    model_config = ConfigDict(frozen=True)

    opened: bool
    job_key: str | None = None
    run_started_at: str | None = None
    session_id: str | None = None
    refusal: DispatchRefusal | None = None
    detail: str | None = None

    def render(self) -> str:
        """The single line a runner writes."""
        return f"{DISPATCH_LINE_PREFIX}{self.model_dump_json(exclude_none=True)}"


def parse_dispatch_line(line: str) -> JobDispatchRecord | None:
    """The record a runner line carries, or None for any other line of its output."""
    stripped = line.strip()
    if not stripped.startswith(DISPATCH_LINE_PREFIX):
        return None
    return JobDispatchRecord.model_validate_json(stripped.removeprefix(DISPATCH_LINE_PREFIX))


class DispatchReporter:
    """Tells a dispatch's launcher, once, what the runner decided."""

    def __init__(self, sink: Callable[[JobDispatchRecord], None]) -> None:
        self._sink = sink
        self._reported = False

    @property
    def reported(self) -> bool:
        """Whether the runner has said what it decided."""
        return self._reported

    def opened(self, job_key: str, run_started_at: str, session_id: str | None = None) -> None:
        """The runner opened this run."""
        self._report(
            JobDispatchRecord(opened=True, job_key=job_key, run_started_at=run_started_at, session_id=session_id)
        )

    def refused(self, refusal: DispatchRefusal, *, job_key: str | None = None, detail: str | None = None) -> None:
        """The runner opened no run, and why."""
        self._report(JobDispatchRecord(opened=False, job_key=job_key, refusal=refusal, detail=detail))

    def _report(self, record: JobDispatchRecord) -> None:
        if self._reported:
            return
        self._reported = True
        self._sink(record)
