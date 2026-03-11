"""System event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_system(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="system.daemon.restarted",
            description="Daemon process restarted on a computer",
            default_level=EventLevel.INFRASTRUCTURE,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["computer", "pid"],
            lifecycle=NotificationLifecycle(creates=True),
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.worker.crashed",
            description="A background worker crashed unexpectedly",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["worker_name", "timestamp"],
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.burst.detected",
            description="A burst of events of the same type was detected within a short window. Payload: event_type, window_start, count",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["event_type", "window_start"],
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.failure_cascade.detected",
            description="Multiple worker crashes detected within a short window. Payload: crash_count, window_start, workers",
            default_level=EventLevel.BUSINESS,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["window_start"],
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.entity.degraded",
            description="Repeated failures detected for the same entity within a short window. Payload: entity, failure_count, window_start",
            default_level=EventLevel.WORKFLOW,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["entity"],
            lifecycle=NotificationLifecycle(
                creates=True, updates=True, group_key="entity", meaningful_fields=["failure_count"]
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.alpha-container.unhealthy",
            description="Alpha container failed repeated health checks and is permanently disabled",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=[],
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.alpha-container.docker-unavailable",
            description="Docker is not available; alpha container subsystem is disabled",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=[],
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
