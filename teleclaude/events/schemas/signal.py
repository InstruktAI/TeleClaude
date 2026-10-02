"""Signal taxonomy event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import (
    EventSchema,
    NotificationLifecycle,
    PayloadField,
    PayloadValueKind,
    SubjectAssignment,
)
from teleclaude.events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


_SUBJECT_ASSIGNMENT_PLATFORM = SubjectAssignment(
    kinds=[], about="the platform or event stream activity represented by this event"
)
_PAYLOAD_FIELDS_SIGNAL_CLUSTER_FORMED: list[PayloadField] = [
    PayloadField(name="cluster_id", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="is_burst", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="is_novel", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="member_count", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="summary", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="tags", kind=PayloadValueKind.ARRAY, nullable=False),
]
_PAYLOAD_FIELDS_SIGNAL_INGEST_RECEIVED: list[PayloadField] = [
    PayloadField(name="fetched_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="item_url", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="published_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="raw_title", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="source_id", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="tags", kind=PayloadValueKind.ARRAY, nullable=False),
]
_PAYLOAD_FIELDS_SIGNAL_SYNTHESIS_READY: list[PayloadField] = [
    PayloadField(name="cluster_id", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="synthesis", kind=PayloadValueKind.OBJECT, nullable=False),
]


def register_signal(catalog: EventCatalog) -> None:
    """Register signal-pipeline event schemas."""
    catalog.register(
        EventSchema(
            event_type="signal.ingest.received",
            description="A single feed item was ingested and normalised.",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SIGNAL_INGEST_RECEIVED,
            default_level=EventLevel.OPERATIONAL,
            domain="signal",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=None,
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="signal.cluster.formed",
            description="A group of related ingested signals formed a cluster.",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SIGNAL_CLUSTER_FORMED,
            default_level=EventLevel.OPERATIONAL,
            domain="signal",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=None,
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="signal.synthesis.ready",
            description="A cluster has been synthesised into a structured artifact.",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SIGNAL_SYNTHESIS_READY,
            default_level=EventLevel.WORKFLOW,
            domain="signal",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                meaningful_fields=["synthesis"],
            ),
            actionable=True,
        )
    )
