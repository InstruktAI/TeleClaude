"""Recurring job event schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.events.catalog import (
    EventSchema,
    LifecycleFamily,
    NotificationLifecycle,
    PayloadField,
    PayloadValueKind,
    SubjectAssignment,
)
from teleclaude.events.envelope import EventHomeKind, EventLevel

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


_SUBJECT_ASSIGNMENT_JOB_PROJECT = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT], about="the project the recurring job run executes for"
)
_PAYLOAD_FIELDS_JOB_RUN_FAILED: list[PayloadField] = [
    PayloadField(name="actionable", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="items", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="job_name", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="message", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="status", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_JOB_RUN_STALLED: list[PayloadField] = [
    PayloadField(name="actionable", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="items", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="job_name", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="message", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="status", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_JOB_RUN_SUCCEEDED: list[PayloadField] = [
    PayloadField(name="actionable", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="items", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="job_name", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="message", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="status", kind=PayloadValueKind.STRING, nullable=False),
]


def register_jobs(catalog: EventCatalog) -> None:
    """Register recurring-job outcome event schemas."""
    catalog.register(
        EventSchema(
            event_type=JobRunEventType.SUCCEEDED,
            description="A recurring job run completed successfully",
            subject_assignment=_SUBJECT_ASSIGNMENT_JOB_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_JOB_RUN_SUCCEEDED,
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
            subject_assignment=_SUBJECT_ASSIGNMENT_JOB_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_JOB_RUN_FAILED,
            default_level=EventLevel.OPERATIONAL,
            domain=JOBS_DOMAIN,
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key=JOB_OUTCOME_GROUP_KEY,
                family=LifecycleFamily.JOB_RUN,
                meaningful_fields=JOB_OUTCOME_MEANINGFUL_FIELDS,
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type=JobRunEventType.STALLED,
            description="A recurring job run stalled before reporting an outcome",
            subject_assignment=_SUBJECT_ASSIGNMENT_JOB_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_JOB_RUN_STALLED,
            default_level=EventLevel.OPERATIONAL,
            domain=JOBS_DOMAIN,
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key=JOB_OUTCOME_GROUP_KEY,
                family=LifecycleFamily.JOB_RUN,
                meaningful_fields=JOB_OUTCOME_MEANINGFUL_FIELDS,
            ),
            actionable=True,
        )
    )
