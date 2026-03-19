"""Event catalog — registry of all known event schemas."""

from __future__ import annotations

from importlib import import_module

from pydantic import BaseModel

from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventLevel, EventVisibility


class NotificationLifecycle(BaseModel):
    """Notification projection semantics for an event type."""

    creates: bool = False
    updates: bool = False
    resolves: bool = False
    group_key: str | None = None
    meaningful_fields: list[str] = []
    silent_fields: list[str] = []


class EventSchema(BaseModel):
    """Schema metadata describing how an event should be classified and projected."""

    event_type: str
    description: str
    default_level: EventLevel
    domain: str
    default_visibility: EventVisibility = EventVisibility.LOCAL
    idempotency_fields: list[str] = []
    lifecycle: NotificationLifecycle | None = None
    actionable: bool = False


class EventCatalog:
    """In-memory registry of known event schemas keyed by event type."""

    def __init__(self) -> None:
        self._registry: dict[str, EventSchema] = {}

    def register(self, schema: EventSchema) -> None:
        """Register an event schema, rejecting duplicate event types."""
        if schema.event_type in self._registry:
            raise ValueError(f"Event type already registered: {schema.event_type}")
        self._registry[schema.event_type] = schema

    def get(self, event_type: str) -> EventSchema | None:
        """Return the schema for an event type, if one is registered."""
        return self._registry.get(event_type)

    def list_all(self) -> list[EventSchema]:
        """Return all registered schemas sorted by event type."""
        return sorted(self._registry.values(), key=lambda s: s.event_type)

    def build_idempotency_key(self, event_type: str, payload: JsonDict) -> str | None:
        """Build the configured idempotency key for an event payload."""
        schema = self._registry.get(event_type)
        if not schema or not schema.idempotency_fields:
            return None
        parts = [event_type] + [str(payload.get(f, "")) for f in schema.idempotency_fields]
        return ":".join(parts)


def build_default_catalog() -> EventCatalog:
    """Build a catalog containing all built-in event schemas."""
    register_all = import_module("teleclaude.events.schemas").register_all
    catalog = EventCatalog()
    register_all(catalog)
    return catalog
