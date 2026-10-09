"""Webhook service data models for event routing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class HookEvent:
    """Standard property bag for all events (internal and inbound external)."""

    source: str  # origin: "agent", "whatsapp", "github", "system", ...
    type: str  # hierarchical dot-separated: "session.started", "tool.completed"
    timestamp: str  # ISO 8601 UTC
    properties: dict[str, str | int | float | bool | list[str] | None] = field(default_factory=dict)
    payload: Mapping[str, object] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the event to JSON for persistence or transport."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> HookEvent:
        """Deserialize a HookEvent from its JSON representation."""
        d = json.loads(data)
        return cls(**d)

    @classmethod
    def now(
        cls,
        source: str,
        event_type: str | None = None,
        properties: dict[str, str | int | float | bool | list[str] | None] | None = None,
        payload: Mapping[str, object] | None = None,
        **legacy_kwargs: object,
    ) -> HookEvent:
        """Create a new event stamped with the current UTC time.

        Accepts legacy callers that still pass `type=` by keyword.
        """
        if event_type is None:
            legacy_type = legacy_kwargs.pop("type", None)
            if not isinstance(legacy_type, str):
                raise TypeError("HookEvent.now() requires an event type")
            event_type = legacy_type
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            raise TypeError(f"Unexpected HookEvent.now() keyword(s): {unexpected}")
        return cls(
            source=source,
            type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            properties=properties or {},
            payload=payload or {},
        )


@dataclass(frozen=True)
class PropertyCriterion:
    """A single property match criterion in a contract."""

    match: str | list[str] | None = None  # exact or multi-value match
    pattern: str | None = None  # wildcard pattern (e.g., "session.*")
    required: bool = True  # must be present; False = documentation-only


@dataclass(frozen=True)
class Target:
    """Delivery target for a contract: the key of a registered in-process handler."""

    handler: str


@dataclass(frozen=True)
class Contract:
    """A declaration of which events a registered handler receives."""

    id: str
    target: Target
    source_criterion: PropertyCriterion | None = None
    type_criterion: PropertyCriterion | None = None
    properties: dict[str, PropertyCriterion] = field(default_factory=dict)
