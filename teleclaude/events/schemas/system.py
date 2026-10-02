"""System event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import (
    EventSchema,
    LifecycleFamily,
    NotificationLifecycle,
    PayloadField,
    PayloadValueKind,
    SubjectAssignment,
)
from teleclaude.events.envelope import EventHomeKind, EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


_SUBJECT_ASSIGNMENT_ENTITY_SUBJECT = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY],
    about="the subject of the failing events correlated by this degradation",
)
_SUBJECT_ASSIGNMENT_PLATFORM = SubjectAssignment(
    kinds=[], about="the platform or event stream activity represented by this event"
)
_SUBJECT_ASSIGNMENT_SESSION_LIFECYCLE = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY],
    about="the recorded home of the session whose lifecycle this event records",
)
_PAYLOAD_FIELDS_AGENT_RUNTIME_RESTART_FAILED: list[PayloadField] = [
    PayloadField(name="computer", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="phase", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="reason", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="restart_group", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="session_id", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_AGENT_RUNTIME_SESSION_ENDED: list[PayloadField] = [
    PayloadField(name="ended_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="session_id", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_CONFIG_EFFECTIVE_UPDATED: list[PayloadField] = [
    PayloadField(name="changed_sections", kind=PayloadValueKind.ARRAY, nullable=False),
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="updated_at", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_BURST_DETECTED: list[PayloadField] = [
    PayloadField(name="count", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="event_type", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="window_start", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_DAEMON_RESTARTED: list[PayloadField] = [
    PayloadField(name="computer", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="pid", kind=PayloadValueKind.INTEGER, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_ENTITY_DEGRADED: list[PayloadField] = [
    PayloadField(name="entity", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="failure_count", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="window_start", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_EVENT_DEAD_LETTERED: list[PayloadField] = [
    PayloadField(name="attempt_count", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="consumer_id", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="dlq_destination", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="failing_stage", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="original_entry_id", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="original_stream", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_FAILURE_CASCADE_DETECTED: list[PayloadField] = [
    PayloadField(name="crash_count", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="window_start", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="workers", kind=PayloadValueKind.ARRAY, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_PROCESS_REAPED: list[PayloadField] = [
    PayloadField(name="lease_expires_at", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="observe_only", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="owner", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="pid", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="reason", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="signature_id", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="signature_name", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_SANDBOX_CONTAINER_DOCKER_UNAVAILABLE: list[PayloadField] = []
_PAYLOAD_FIELDS_SYSTEM_SANDBOX_CONTAINER_UNHEALTHY: list[PayloadField] = []
_PAYLOAD_FIELDS_SYSTEM_SESSION_BOOTSTRAP_FAILED: list[PayloadField] = [
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="reason", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="session_id", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_SYSTEM_WORKER_CRASHED: list[PayloadField] = []


def register_system(catalog: EventCatalog) -> None:
    """Register core system event schemas."""
    catalog.register(
        EventSchema(
            event_type="config.effective.updated",
            description="Effective project configuration changed and may affect workflow runner eligibility",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_CONFIG_EFFECTIVE_UPDATED,
            default_level=EventLevel.WORKFLOW,
            domain="config",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="project_path",
                family=LifecycleFamily.CONFIG_SYNC,
                meaningful_fields=["project_path"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="agent_runtime.session.ended",
            description="A session was closed and may require lifecycle-runner re-evaluation of its todo",
            subject_assignment=_SUBJECT_ASSIGNMENT_SESSION_LIFECYCLE,
            payload_fields=_PAYLOAD_FIELDS_AGENT_RUNTIME_SESSION_ENDED,
            default_level=EventLevel.WORKFLOW,
            domain="agent_runtime",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                resolves=True,
                group_key="session_id",
                family=LifecycleFamily.AGENT_SESSION_LIFECYCLE,
                meaningful_fields=["session_id", "project_path"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="agent_runtime.restart.failed",
            description="An agent restart failed before the agent could resume, and the session was kept alive for inspection",
            subject_assignment=_SUBJECT_ASSIGNMENT_SESSION_LIFECYCLE,
            payload_fields=_PAYLOAD_FIELDS_AGENT_RUNTIME_RESTART_FAILED,
            default_level=EventLevel.OPERATIONAL,
            domain="agent_runtime",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="restart_group",
                family=LifecycleFamily.AGENT_RESTART,
                meaningful_fields=["reason", "phase"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.daemon.restarted",
            description="Daemon process restarted on a computer",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_DAEMON_RESTARTED,
            default_level=EventLevel.INFRASTRUCTURE,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.worker.crashed",
            description="A background worker crashed unexpectedly",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_WORKER_CRASHED,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.session.bootstrap_failed",
            description="A session's tmux/identity bootstrap failed, stranding it before it reached active",
            subject_assignment=_SUBJECT_ASSIGNMENT_SESSION_LIFECYCLE,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_SESSION_BOOTSTRAP_FAILED,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.process.reaped",
            description="Process janitor reaped or observed a reapable process",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_PROCESS_REAPED,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                meaningful_fields=[
                    "pid",
                    "signature_id",
                    "signature_name",
                    "reason",
                    "observe_only",
                    "owner",
                    "lease_expires_at",
                ],
            ),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.event.dead_lettered",
            description="An event exhausted its retry ceiling and transitioned to the dead-letter destination",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_EVENT_DEAD_LETTERED,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.burst.detected",
            description=(
                "A burst of events of the same type was detected within a short window. "
                "Payload: event_type, window_start, count"
            ),
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_BURST_DETECTED,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.failure_cascade.detected",
            description=(
                "Multiple worker crashes detected within a short window. Payload: crash_count, window_start, workers"
            ),
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_FAILURE_CASCADE_DETECTED,
            default_level=EventLevel.BUSINESS,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.entity.degraded",
            description=(
                "Repeated failures detected for the same entity within a short window. "
                "Payload: entity, failure_count, window_start"
            ),
            subject_assignment=_SUBJECT_ASSIGNMENT_ENTITY_SUBJECT,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_ENTITY_DEGRADED,
            default_level=EventLevel.WORKFLOW,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="entity",
                family=LifecycleFamily.ENTITY_DEGRADATION,
                meaningful_fields=["failure_count"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.sandbox-container.unhealthy",
            description="Sandbox container failed repeated health checks and is permanently disabled",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_SANDBOX_CONTAINER_UNHEALTHY,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.sandbox-container.docker-unavailable",
            description="Docker is not available; sandbox container subsystem is disabled",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SYSTEM_SANDBOX_CONTAINER_DOCKER_UNAVAILABLE,
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
