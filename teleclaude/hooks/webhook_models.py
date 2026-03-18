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
    """Delivery target for a contract."""

    handler: str | None = None  # internal handler key (registered callable)
    url: str | None = None  # external webhook URL
    secret: str | None = None  # HMAC signing key for external targets


@dataclass(frozen=True)
class ContractMetadata:
    """Lifecycle metadata for a webhook contract."""

    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None  # ISO 8601 UTC; None = never expires
    source: str = "api"  # "config", "api", "programmatic"


@dataclass(init=False)
class Contract:
    """A subscriber's published declaration of need."""

    id: str
    target: Target
    source_criterion: PropertyCriterion | None
    type_criterion: PropertyCriterion | None
    properties: dict[str, PropertyCriterion]
    _metadata: ContractMetadata = field(init=False, repr=False)

    def __init__(
        self,
        *,
        target: Target,
        contract_id: str | None = None,
        properties: dict[str, PropertyCriterion] | None = None,
        **kwargs: object,
    ) -> None:
        resolved_id = kwargs.pop("id", contract_id)
        if not isinstance(resolved_id, str):
            raise TypeError("Contract requires id")

        source_criterion = kwargs.pop("source_criterion", None)
        type_criterion = kwargs.pop("type_criterion", None)
        active = kwargs.pop("active", True)
        created_at = kwargs.pop("created_at", None)
        expires_at = kwargs.pop("expires_at", None)
        source = kwargs.pop("source", "api")
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected Contract keyword(s): {unexpected}")

        self.id = resolved_id
        self.target = target
        self.source_criterion = source_criterion
        self.type_criterion = type_criterion
        self.properties = {} if properties is None else dict(properties)
        self._metadata = ContractMetadata(
            active=active,
            created_at=datetime.now(UTC).isoformat() if created_at is None else created_at,
            expires_at=expires_at,
            source=source,
        )

    @property
    def active(self) -> bool:
        """Return whether the contract is active."""
        return self._metadata.active

    @property
    def created_at(self) -> str:
        """Return when the contract was created."""
        return self._metadata.created_at

    @property
    def expires_at(self) -> str | None:
        """Return the contract expiry time, if any."""
        return self._metadata.expires_at

    @property
    def source(self) -> str:
        """Return where the contract was created from."""
        return self._metadata.source

    @property
    def is_expired(self) -> bool:
        """Return True when the contract expiry time has passed."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= datetime.fromisoformat(self.expires_at)

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
            "expires_at": self.expires_at,
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
            expires_at=d.get("expires_at"),
            source=d.get("source", "api"),
        )
