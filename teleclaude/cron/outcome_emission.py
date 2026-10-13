"""Job-run outcomes as events: the pending emission a closed run owes and its delivery through the event producer."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Final

from jobs.base import JobResult
from teleclaude.core.models import HumanActionIntent
from teleclaude.cron.state import CronState, JobRunStatus, PendingEmission, project_slug_for_job_key
from teleclaude.events.envelope import (
    EventHomeKind,
    EventHomeMarker,
    EventHomeRef,
    EventLevel,
    EventVisibility,
    occurrence_id,
)
from teleclaude.events.producer import ensure_event_producer
from teleclaude.events.references import JobRef
from teleclaude.events.schemas.jobs import JobRunData, JobRunEventType, JobRunFailed, JobRunStalled, JobRunSucceeded
from teleclaude.events.wire import LegacyFacts


def pending_emission_for_result(
    job_name: str,
    result: JobResult,
    *,
    run_started_at: datetime,
) -> PendingEmission:
    status = JobRunStatus.SUCCESS if result.success else JobRunStatus.FAILED
    event_type = JobRunEventType.SUCCEEDED if result.success else JobRunEventType.FAILED
    return PendingEmission(
        idempotency_key=f"{job_name}:{run_started_at.isoformat()}",
        event_type=event_type.value,
        job_name=job_name,
        status=status,
        message=result.message,
        items=result.items_processed,
        actionable=not result.success,
        run_started_at=run_started_at.isoformat(),
    )


def pending_emission_for_stall(job_name: str, *, run_started_at: datetime, message: str) -> PendingEmission:
    return PendingEmission(
        idempotency_key=f"{job_name}:{run_started_at.isoformat()}",
        event_type=JobRunEventType.STALLED.value,
        job_name=job_name,
        status=JobRunStatus.STALLED,
        message=message,
        items=0,
        actionable=True,
        run_started_at=run_started_at.isoformat(),
    )


def _event_level_for_status(status: JobRunStatus) -> EventLevel:
    if status is JobRunStatus.SUCCESS:
        return EventLevel.WORKFLOW
    return EventLevel.OPERATIONAL


_JOB_RUN_EVENTS: Final[Mapping[JobRunEventType, type[JobRunSucceeded | JobRunFailed | JobRunStalled]]] = {
    JobRunEventType.SUCCEEDED: JobRunSucceeded,
    JobRunEventType.FAILED: JobRunFailed,
    JobRunEventType.STALLED: JobRunStalled,
}


def _event_for_pending_emission(
    emission: PendingEmission,
) -> tuple[JobRunSucceeded | JobRunFailed | JobRunStalled, LegacyFacts]:
    """Build the job-run outcome a pending emission reports: about the job, with the run start as data."""
    human_action = None
    if emission.status in (JobRunStatus.FAILED, JobRunStatus.STALLED):
        human_action = HumanActionIntent(
            topic="Recurring job needs attention",
            summary=emission.message,
            action="Investigate the job",
        )
    project_slug = project_slug_for_job_key(emission.job_name)
    home = EventHomeRef(EventHomeKind.PROJECT, project_slug) if project_slug is not None else EventHomeMarker.UNKNOWN
    event_class = _JOB_RUN_EVENTS[JobRunEventType(emission.event_type)]
    event = event_class(
        id=occurrence_id(emission.idempotency_key, emission.event_type),
        subject=JobRef(emission.job_name),
        home=home,
        data=JobRunData(
            job_name=emission.job_name,
            status=emission.status.value,
            message=emission.message,
            items=emission.items,
            run_started_at=emission.run_started_at,
        ),
    )
    legacy = LegacyFacts(
        producer="cron.runner",
        level=_event_level_for_status(emission.status),
        domain="jobs",
        description=emission.message,
        visibility=EventVisibility.CLUSTER,
        entity=emission.job_name,
        idempotency_key=emission.idempotency_key,
        human_action=human_action,
        payload_extras={"actionable": emission.actionable},
    )
    return event, legacy


def drain_pending_emissions(state: CronState) -> None:
    pending = state.iter_pending_emissions()
    if not pending:
        return
    producer = ensure_event_producer()

    async def _drain() -> list[str]:
        published: list[str] = []
        for emission in pending:
            await producer.emit(*_event_for_pending_emission(emission))
            published.append(emission.idempotency_key)
        return published

    published_keys = asyncio.run(_drain())
    for key in published_keys:
        state.remove_pending_emission(key, persist=False)
    state.save()
