"""Webhook service data models for event routing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class HookEvent:
    """Standard property bag for all events (internal and inbound external)."""

    source: str  # origin: "agent", "whatsapp", "github", "system", ...
    type: str  # hierarchical dot-separated: "session.started", "tool.completed"
    timestamp: str  # ISO 8601 UTC
    properties: dict[str, str | int | float | bool | list[str] | None] = field(default_factory=dict)
    payload: Mapping[str, object] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> HookEvent:
        d = json.loads(data)
        return cls(**d)

    @classmethod
    def now(
        cls,
        source: str,
        type: str,
        properties: dict[str, str | int | float | bool | list[str] | None] | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> HookEvent:
        return cls(
            source=source,
            type=type,
            timestamp=datetime.now(timezone.utc).isoformat(),
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
    """Delivery target for a contract."""

    handler: str | None = None  # internal handler key (registered callable)
    url: str | None = None  # external webhook URL
    secret: str | None = None  # HMAC signing key for external targets


@dataclass
class Contract:
    """A subscriber's published declaration of need."""

    id: str
    target: Target
    source_criterion: PropertyCriterion | None = None
    type_criterion: PropertyCriterion | None = None
    properties: dict[str, PropertyCriterion] = field(default_factory=dict)
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "api"  # "config", "api", "programmatic"

    def to_json(self) -> str:
        """Serialize to JSON for DB storage."""
        d = {
            "id": self.id,
            "target": {"handler": self.target.handler, "url": self.target.url, "secret": self.target.secret},
            "source_criterion": asdict(self.source_criterion) if self.source_criterion else None,
            "type_criterion": asdict(self.type_criterion) if self.type_criterion else None,
            "properties": {k: asdict(v) for k, v in self.properties.items()},
            "active": self.active,
            "created_at": self.created_at,
            "source": self.source,
        }
        return json.dumps(d)

    @classmethod
    def from_json(cls, data: str) -> Contract:
        """Deserialize from JSON."""
        d = json.loads(data)
        target = Target(**d["target"])
        source_criterion = PropertyCriterion(**d["source_criterion"]) if d.get("source_criterion") else None
        type_criterion = PropertyCriterion(**d["type_criterion"]) if d.get("type_criterion") else None
        properties = {k: PropertyCriterion(**v) for k, v in d.get("properties", {}).items()}
        return cls(
            id=d["id"],
            target=target,
            source_criterion=source_criterion,
            type_criterion=type_criterion,
            properties=properties,
            active=d.get("active", True),
            created_at=d.get("created_at", ""),
            source=d.get("source", "api"),
        )
