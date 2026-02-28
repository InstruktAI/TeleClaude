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
