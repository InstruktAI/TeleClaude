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
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

#: Current envelope schema generation. Used as the default for EventEnvelope.version.
SCHEMA_VERSION: int = 3


class EventVisibility(str, Enum):
    """Visibility scope for an event."""

    LOCAL = "local"
    CLUSTER = "cluster"
    PUBLIC = "public"


class EventLevel(IntEnum):
    """Priority level for event routing and notification decisions."""

    INFRASTRUCTURE = 0
    OPERATIONAL = 1
    WORKFLOW = 2
    BUSINESS = 3


class ActionDescriptor(BaseModel):
    """Human- or agent-facing action affordance attached to an event."""

    description: str
    produces: str
    outcome_shape: dict[str, str] | None = None


class EventEnvelope(BaseModel):
    """Canonical event payload stored on the stream and in downstream projections."""

    model_config = ConfigDict(extra="allow")

    # Identity
    event: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = SCHEMA_VERSION
    source: str
    originating_computer: str | None = None
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

    @field_validator("event_id")
    @classmethod
    def _validate_event_id(cls, value: str) -> str:
        """Reject empty event identities at the envelope boundary."""
        if not value.strip():
            raise ValueError("event_id must be a non-empty string")
        return value

    def to_stream_dict(self) -> dict[str, str]:
        """Serialize to a flat string dict for Redis XADD.

        Extra fields (beyond declared model fields) are JSON-encoded into a
        single ``_extra`` key to preserve the flat dict[str, str] constraint.
        """
        dumped = self.model_dump(mode="json")
        d: dict[str, str] = {
            "event": self.event,
            "event_id": self.event_id,
            "version": str(self.version),
            "source": self.source,
            "originating_computer": self.originating_computer or "",
            "timestamp": cast(str, dumped["timestamp"]),
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
        legacy_event_id = extra.pop("event_id", None)
        # Migration affordance: pre-fix v1 stream entries lack top-level event_id.
        # Synthesizing one keeps upgrade-time replay out of the DLQ; new producers
        # always serialize event_id and should never rely on this fallback.
        event_id = d.get("event_id") or (legacy_event_id if isinstance(legacy_event_id, str) else "") or str(uuid4())

        return cls(
            event=d["event"],
            event_id=event_id,
            version=int(d.get("version", str(SCHEMA_VERSION))),
            source=d["source"],
            originating_computer=d.get("originating_computer") or None,
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


EventEnvelope.model_rebuild()
