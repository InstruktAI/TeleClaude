"""Event catalog — registry of all known event schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from teleclaude_events.envelope import EventLevel, EventVisibility


class NotificationLifecycle(BaseModel):
    creates: bool = False
    updates: bool = False
    resolves: bool = False
    group_key: str | None = None
    meaningful_fields: list[str] = []
    silent_fields: list[str] = []


class EventSchema(BaseModel):
    event_type: str
    description: str
    default_level: EventLevel
    domain: str
    default_visibility: EventVisibility = EventVisibility.LOCAL
    idempotency_fields: list[str] = []
    lifecycle: NotificationLifecycle | None = None
    actionable: bool = False


class EventCatalog:
    def __init__(self) -> None:
        self._registry: dict[str, EventSchema] = {}

    def register(self, schema: EventSchema) -> None:
        if schema.event_type in self._registry:
            raise ValueError(f"Event type already registered: {schema.event_type}")
        self._registry[schema.event_type] = schema

    def get(self, event_type: str) -> EventSchema | None:
        return self._registry.get(event_type)

    def list_all(self) -> list[EventSchema]:
        return sorted(self._registry.values(), key=lambda s: s.event_type)

    def build_idempotency_key(self, event_type: str, payload: dict[str, Any]) -> str | None:
        schema = self._registry.get(event_type)
        if not schema or not schema.idempotency_fields:
            return None
        parts = [event_type] + [str(payload.get(f, "")) for f in schema.idempotency_fields]
        return ":".join(parts)


def build_default_catalog() -> EventCatalog:
    from teleclaude_events.schemas import register_all

    catalog = EventCatalog()
    register_all(catalog)
    return catalog
