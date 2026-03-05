"""Schema evolution event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema
from teleclaude_events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_schema(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="schema.proposed",
            description="A schema change was proposed for adoption",
            default_level=EventLevel.OPERATIONAL,
            domain="schema",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["schema_id", "version"],
        )
    )
    catalog.register(
        EventSchema(
            event_type="schema.adopted",
            description="A proposed schema change was merged and is now active",
            default_level=EventLevel.OPERATIONAL,
            domain="schema",
            default_visibility=EventVisibility.CLUSTER,
            idempotency_fields=["schema_id", "version"],
        )
    )
