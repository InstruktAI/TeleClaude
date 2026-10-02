"""Node lifecycle event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, PayloadField, SubjectAssignment
from teleclaude.events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


_SUBJECT_ASSIGNMENT_PLATFORM = SubjectAssignment(
    kinds=[], about="the platform or event stream activity represented by this event"
)
_PAYLOAD_FIELDS_NODE_ALIVE: list[PayloadField] = []
_PAYLOAD_FIELDS_NODE_DESCRIPTOR_UPDATED: list[PayloadField] = []
_PAYLOAD_FIELDS_NODE_LEAVING: list[PayloadField] = []


def register_node(catalog: EventCatalog) -> None:
    """Register cluster node lifecycle event schemas."""
    catalog.register(
        EventSchema(
            event_type="node.alive",
            description="Node heartbeat or presence announcement",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_NODE_ALIVE,
            default_level=EventLevel.INFRASTRUCTURE,
            domain="node",
            default_visibility=EventVisibility.CLUSTER,
        )
    )
    catalog.register(
        EventSchema(
            event_type="node.leaving",
            description="Node is departing the cluster gracefully",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_NODE_LEAVING,
            default_level=EventLevel.INFRASTRUCTURE,
            domain="node",
            default_visibility=EventVisibility.CLUSTER,
        )
    )
    catalog.register(
        EventSchema(
            event_type="node.descriptor_updated",
            description="Node metadata or capabilities changed",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_NODE_DESCRIPTOR_UPDATED,
            default_level=EventLevel.OPERATIONAL,
            domain="node",
            default_visibility=EventVisibility.CLUSTER,
        )
    )
