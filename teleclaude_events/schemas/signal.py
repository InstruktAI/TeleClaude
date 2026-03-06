"""Signal taxonomy event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_signal(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="signal.ingest.received",
            description="A single feed item was ingested and normalised.",
            default_level=EventLevel.OPERATIONAL,
            domain="signal",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["source_id", "item_url"],
            lifecycle=None,
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="signal.cluster.formed",
            description="A group of related ingested signals formed a cluster.",
            default_level=EventLevel.OPERATIONAL,
            domain="signal",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["cluster_id"],
            lifecycle=None,
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="signal.synthesis.ready",
            description="A cluster has been synthesised into a structured artifact.",
            default_level=EventLevel.WORKFLOW,
            domain="signal",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["cluster_id"],
            lifecycle=NotificationLifecycle(
                creates=True,
                meaningful_fields=["synthesis"],
            ),
            actionable=True,
        )
    )
