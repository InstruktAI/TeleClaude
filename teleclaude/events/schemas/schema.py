"""Schema evolution event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, PayloadField, SubjectAssignment
from teleclaude.events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


_SUBJECT_ASSIGNMENT_PLATFORM = SubjectAssignment(
    kinds=[], about="the platform or event stream activity represented by this event"
)
_PAYLOAD_FIELDS_SCHEMA_ADOPTED: list[PayloadField] = []
_PAYLOAD_FIELDS_SCHEMA_PROPOSED: list[PayloadField] = []


def register_schema(catalog: EventCatalog) -> None:
    """Register schema-evolution event schemas."""
    catalog.register(
        EventSchema(
            event_type="schema.proposed",
            description="A schema change was proposed for adoption",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SCHEMA_PROPOSED,
            default_level=EventLevel.OPERATIONAL,
            domain="schema",
            default_visibility=EventVisibility.CLUSTER,
        )
    )
    catalog.register(
        EventSchema(
            event_type="schema.adopted",
            description="A proposed schema change was merged and is now active",
            subject_assignment=_SUBJECT_ASSIGNMENT_PLATFORM,
            payload_fields=_PAYLOAD_FIELDS_SCHEMA_ADOPTED,
            default_level=EventLevel.OPERATIONAL,
            domain="schema",
            default_visibility=EventVisibility.CLUSTER,
        )
    )
