"""Notification meta-event schemas."""

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


_SUBJECT_ASSIGNMENT_NOTIFICATION_SUBJECT = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY],
    about="the subject of the event that produced this notification",
)
_PAYLOAD_FIELDS_NOTIFICATION_ESCALATION: list[PayloadField] = [
    PayloadField(name="escalation_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="reason", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_NOTIFICATION_RESOLUTION: list[PayloadField] = [
    PayloadField(name="escalation_id", kind=PayloadValueKind.ANY, nullable=False),
]


def register_notification(catalog: EventCatalog) -> None:
    """Register notification meta-event schemas."""
    catalog.register(
        EventSchema(
            event_type="notification.escalation",
            description="An issue was escalated to a human for action",
            subject_assignment=_SUBJECT_ASSIGNMENT_NOTIFICATION_SUBJECT,
            payload_fields=_PAYLOAD_FIELDS_NOTIFICATION_ESCALATION,
            default_level=EventLevel.BUSINESS,
            domain="notification",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["escalation_id", "reason"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="notification.resolution",
            description="An escalation was resolved",
            subject_assignment=_SUBJECT_ASSIGNMENT_NOTIFICATION_SUBJECT,
            payload_fields=_PAYLOAD_FIELDS_NOTIFICATION_RESOLUTION,
            default_level=EventLevel.WORKFLOW,
            domain="notification",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="escalation_id", family=LifecycleFamily.NOTIFICATION_ESCALATION
            ),
        )
    )
