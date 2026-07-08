"""Recurring job event schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


JOBS_DOMAIN = "jobs"
JOB_OUTCOME_GROUP_KEY = "job_name"
JOB_OUTCOME_MEANINGFUL_FIELDS = ["job_name", "status", "message"]


class JobRunEventType(StrEnum):
    """Event types emitted by the recurring-job run lifecycle."""

    SUCCEEDED = "job.run.succeeded"
    FAILED = "job.run.failed"
    STALLED = "job.run.stalled"


def register_jobs(catalog: EventCatalog) -> None:
    """Register recurring-job outcome event schemas."""
    catalog.register(
        EventSchema(
            event_type=JobRunEventType.SUCCEEDED,
            description="A recurring job run completed successfully",
            default_level=EventLevel.WORKFLOW,
            domain=JOBS_DOMAIN,
            lifecycle=NotificationLifecycle(creates=False),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type=JobRunEventType.FAILED,
            description="A recurring job run failed and requires operator attention",
            default_level=EventLevel.OPERATIONAL,
            domain=JOBS_DOMAIN,
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key=JOB_OUTCOME_GROUP_KEY,
                meaningful_fields=JOB_OUTCOME_MEANINGFUL_FIELDS,
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type=JobRunEventType.STALLED,
            description="A recurring job run stalled before reporting an outcome",
            default_level=EventLevel.OPERATIONAL,
            domain=JOBS_DOMAIN,
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key=JOB_OUTCOME_GROUP_KEY,
                meaningful_fields=JOB_OUTCOME_MEANINGFUL_FIELDS,
            ),
            actionable=True,
        )
    )
