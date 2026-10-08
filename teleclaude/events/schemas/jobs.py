"""Recurring job event declarations: one lifecycle family whose subject is the job, not the single run."""

from __future__ import annotations

from enum import StrEnum

from teleclaude.events.catalog import DeclaredEvent, EventData, LifecycleState, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import JobRef

JOB_RUN_FAMILY = "teleclaude.job.run"


class JobRunEventType(StrEnum):
    """Event types emitted by the recurring-job run lifecycle."""

    SUCCEEDED = "teleclaude.job.run.succeeded"
    FAILED = "teleclaude.job.run.failed"
    STALLED = "teleclaude.job.run.stalled"


class JobRunData(EventData):
    """The facts of one run: the run start identifies the occurrence of the job's state."""

    items: int
    job_name: str
    message: str
    run_started_at: str
    status: str


class JobRunSucceeded(PlatformEvent[JobRef, JobRunData]):
    FAMILY = JOB_RUN_FAMILY
    STATE = LifecycleState.SUCCEEDED
    DESCRIPTION = "A recurring job run completed successfully"
    HOME_KINDS = (EventHomeKind.PROJECT,)


class JobRunFailed(PlatformEvent[JobRef, JobRunData]):
    FAMILY = JOB_RUN_FAMILY
    STATE = LifecycleState.FAILED
    DESCRIPTION = "A recurring job run failed and requires operator attention"
    HOME_KINDS = (EventHomeKind.PROJECT,)


class JobRunStalled(PlatformEvent[JobRef, JobRunData]):
    FAMILY = JOB_RUN_FAMILY
    STATE = LifecycleState.STALLED
    DESCRIPTION = "A recurring job run stalled before reporting an outcome"
    HOME_KINDS = (EventHomeKind.PROJECT,)


DECLARED: tuple[DeclaredEvent, ...] = (JobRunSucceeded, JobRunFailed, JobRunStalled)
