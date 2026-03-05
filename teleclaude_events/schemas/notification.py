"""Notification meta-event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_notification(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="notification.escalation",
            description="An issue was escalated to a human for action",
            default_level=EventLevel.BUSINESS,
            domain="notification",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["escalation_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["escalation_id", "reason"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="notification.resolution",
            description="An escalation was resolved",
            default_level=EventLevel.WORKFLOW,
            domain="notification",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["escalation_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="escalation_id"),
        )
    )
