"""Content lifecycle event schemas."""

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


_SUBJECT_ASSIGNMENT_SESSION_HOME = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY],
    about="the recorded home of the session whose work this event records",
)
_PAYLOAD_FIELDS_CONTENT_DUMPED: list[PayloadField] = [
    PayloadField(name="author", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="inbox_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="tags", kind=PayloadValueKind.ARRAY, nullable=False),
]
_PAYLOAD_FIELDS_CONTENT_PUBLISHED: list[PayloadField] = [
    PayloadField(name="content_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_CONTENT_REFINED: list[PayloadField] = [
    PayloadField(name="content_id", kind=PayloadValueKind.ANY, nullable=False),
]


def register_content(catalog: EventCatalog) -> None:
    """Register content-domain event schemas."""
    catalog.register(
        EventSchema(
            event_type="content.dumped",
            description="Raw content was captured and queued for processing",
            subject_assignment=_SUBJECT_ASSIGNMENT_SESSION_HOME,
            payload_fields=_PAYLOAD_FIELDS_CONTENT_DUMPED,
            default_level=EventLevel.WORKFLOW,
            domain="content",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["content_id"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="content.refined",
            description="Content was processed or edited",
            subject_assignment=_SUBJECT_ASSIGNMENT_SESSION_HOME,
            payload_fields=_PAYLOAD_FIELDS_CONTENT_REFINED,
            default_level=EventLevel.WORKFLOW,
            domain="content",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                updates=True, group_key="content_id", family=LifecycleFamily.CONTENT_LIFECYCLE
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="content.published",
            description="Content was made available externally",
            subject_assignment=_SUBJECT_ASSIGNMENT_SESSION_HOME,
            payload_fields=_PAYLOAD_FIELDS_CONTENT_PUBLISHED,
            default_level=EventLevel.BUSINESS,
            domain="content",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="content_id", family=LifecycleFamily.CONTENT_LIFECYCLE
            ),
        )
    )
