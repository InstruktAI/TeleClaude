"""Event envelope — the core data model for all events in the platform.

SCHEMA_VERSION tracks the envelope structure generation. Bump it when fields
are added, removed, or changed in a way that affects the wire format. This is
distinct from the package semver: it tracks the schema generation, not the
full release.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum, IntEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

#: Current envelope schema generation. Used as the default for EventEnvelope.version.
SCHEMA_VERSION: int = 1


class EventVisibility(str, Enum):
    LOCAL = "local"
    CLUSTER = "cluster"
    PUBLIC = "public"


class EventLevel(IntEnum):
    INFRASTRUCTURE = 0
    OPERATIONAL = 1
    WORKFLOW = 2
    BUSINESS = 3


class ActionDescriptor(BaseModel):
    description: str
    produces: str
    outcome_shape: dict[str, str] | None = None


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Identity
    event: str
    version: int = SCHEMA_VERSION
    source: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    idempotency_key: str | None = None
    # Semantic
    level: EventLevel
    domain: str = ""
    entity: str | None = None
    description: str = ""
    visibility: EventVisibility = EventVisibility.LOCAL
    # Data  # guard: loose-dict - JsonValue is recursive; pydantic cannot resolve it without infinite recursion
    payload: dict[str, Any] = Field(default_factory=dict)
    # Affordances (structural, not processed in core phase)
    actions: dict[str, ActionDescriptor] | None = None
    # Resolution
    terminal_when: str | None = None
    resolution_shape: dict[str, str] | None = None

    def to_stream_dict(self) -> dict[str, str]:
        """Serialize to a flat string dict for Redis XADD.

        Extra fields (beyond declared model fields) are JSON-encoded into a
        single ``_extra`` key to preserve the flat dict[str, str] constraint.
        """
        d: dict[str, str] = {
            "event": self.event,
            "version": str(self.version),
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "idempotency_key": self.idempotency_key or "",
            "level": str(int(self.level)),
            "domain": self.domain,
            "entity": self.entity or "",
            "description": self.description,
            "visibility": self.visibility.value,
            "payload": json.dumps(self.payload),
            "actions": json.dumps({k: v.model_dump() for k, v in self.actions.items()}) if self.actions else "",
            "terminal_when": self.terminal_when or "",
            "resolution_shape": json.dumps(self.resolution_shape) if self.resolution_shape else "",
        }
        extra = self.model_extra
        if extra:
            d["_extra"] = json.dumps(extra)
        return d

    @classmethod
    def from_stream_dict(cls, data: dict[bytes, bytes] | dict[str, str]) -> EventEnvelope:
        """Deserialize from Redis stream entry dict."""

        def _str(v: bytes | str) -> str:
            return v.decode() if isinstance(v, bytes) else v

        d = {_str(k): _str(v) for k, v in data.items()}

        payload = cast(dict[str, JsonValue], json.loads(d.get("payload", "{}")) if d.get("payload") else {})
        actions_raw = d.get("actions", "")
        actions = None
        if actions_raw:
            actions = {k: ActionDescriptor(**v) for k, v in json.loads(actions_raw).items()}
        resolution_shape_raw = d.get("resolution_shape", "")
        resolution_shape = json.loads(resolution_shape_raw) if resolution_shape_raw else None

        extra: dict[str, JsonValue] = {}
        extra_raw = d.get("_extra", "")
        if extra_raw:
            extra = cast(dict[str, JsonValue], json.loads(extra_raw))

        return cls(
            event=d["event"],
            version=int(d.get("version", str(SCHEMA_VERSION))),
            source=d["source"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            idempotency_key=d.get("idempotency_key") or None,
            level=EventLevel(int(d["level"])),
            domain=d.get("domain", ""),
            entity=d.get("entity") or None,
            description=d.get("description", ""),
            visibility=EventVisibility(d.get("visibility", "local")),
            payload=payload,
            actions=actions,
            terminal_when=d.get("terminal_when") or None,
            resolution_shape=resolution_shape,
            **extra,
        )
