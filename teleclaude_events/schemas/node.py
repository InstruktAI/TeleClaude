"""Node lifecycle event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema
from teleclaude_events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_node(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="node.alive",
            description="Node heartbeat or presence announcement",
            default_level=EventLevel.INFRASTRUCTURE,
            domain="node",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["node_id"],
        )
    )
    catalog.register(
        EventSchema(
            event_type="node.leaving",
            description="Node is departing the cluster gracefully",
            default_level=EventLevel.INFRASTRUCTURE,
            domain="node",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["node_id"],
        )
    )
    catalog.register(
        EventSchema(
            event_type="node.descriptor_updated",
            description="Node metadata or capabilities changed",
            default_level=EventLevel.OPERATIONAL,
            domain="node",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["node_id"],
        )
    )
