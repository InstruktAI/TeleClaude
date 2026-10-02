"""Event envelope — the core data model for all events in the platform.

SCHEMA_VERSION tracks the envelope structure generation. Bump it when fields
are added, removed, or changed in a way that affects the wire format. This is
distinct from the package semver: it tracks the schema generation, not the
full release.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, IntEnum, StrEnum
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef, SubjectSource
from teleclaude.core.models import HumanActionIntent
from teleclaude.slug import validate_slug

#: Current envelope schema generation. Used as the default for EventEnvelope.version.
SCHEMA_VERSION: int = 5
_HUMAN_ACTION_STREAM_KEY = "human_action"
_ORIGIN_SESSION_STREAM_KEY = "originating_session_id"
_ORIGIN_HOME_STREAM_KEY = "origin_home"
_SUBJECT_STREAM_KEY = "subject"
_SUBJECT_OWNER_STREAM_KEY = "subject_owner"
_EVENT_HOME_KIND_TYPE_ERROR = "event home kind must be an EventHomeKind"
_EVENT_HOME_SUBJECT_REF_ERROR = "event homes must name registered project, person, or company subjects"
_EVENT_OWNER_KIND_TYPE_ERROR = "event owner kind must be an EventOwnerKind"
_EVENT_OWNER_SUBJECT_REF_ERROR = "event owners must name registered company or person subjects"


class EventSubjectMarker(StrEnum):
    """Explicit subject states that are not registered homes."""

    NONE = "none"
    UNKNOWN = "unknown"


class EventSubjectOwnerMarker(StrEnum):
    """Explicit project-owner states that are not registry references."""

    NONE = "none"
    OWNERLESS = "ownerless"
    UNRESOLVED = "unresolved"


class EventHomeKind(StrEnum):
    """Configuration homes that may appear as an event subject or origin."""

    PROJECT = "project"
    PERSON = "person"
    COMPANY = "company"


class EventOwnerKind(StrEnum):
    """Registered project-owner kinds that may appear on an event."""

    COMPANY = "company"
    PERSON = "person"


@dataclass(frozen=True)
class EventHomeRef:
    """One registered project, person, or company in the event vocabulary."""

    kind: EventHomeKind
    instance: str

    def __post_init__(self) -> None:
        if type(self.kind) is not EventHomeKind:
            raise TypeError(_EVENT_HOME_KIND_TYPE_ERROR)
        validate_slug(self.instance)

    def to_token(self) -> str:
        return SubjectRef(ConfigSubjectKind(self.kind.value), self.instance).to_token()

    @classmethod
    def from_token(cls, token: str) -> EventHomeRef:
        return cls.from_subject_ref(SubjectRef.from_token(token))

    @classmethod
    def from_subject_ref(cls, subject: SubjectRef) -> EventHomeRef:
        if subject.source is not SubjectSource.REGISTRY or subject.instance is None:
            raise ValueError(_EVENT_HOME_SUBJECT_REF_ERROR)
        try:
            kind = EventHomeKind(subject.kind.value)
        except ValueError as exc:
            raise ValueError(_EVENT_HOME_SUBJECT_REF_ERROR) from exc
        return cls(kind=kind, instance=subject.instance)


@dataclass(frozen=True)
class EventOwnerRef:
    """One registered company or person that owns an event's project subject."""

    kind: EventOwnerKind
    instance: str

    def __post_init__(self) -> None:
        if type(self.kind) is not EventOwnerKind:
            raise TypeError(_EVENT_OWNER_KIND_TYPE_ERROR)
        validate_slug(self.instance)

    def to_token(self) -> str:
        return SubjectRef(ConfigSubjectKind(self.kind.value), self.instance).to_token()

    @classmethod
    def from_token(cls, token: str) -> EventOwnerRef:
        return cls.from_subject_ref(SubjectRef.from_token(token))

    @classmethod
    def from_subject_ref(cls, subject: SubjectRef) -> EventOwnerRef:
        if subject.source is not SubjectSource.REGISTRY or subject.instance is None:
            raise ValueError(_EVENT_OWNER_SUBJECT_REF_ERROR)
        try:
            kind = EventOwnerKind(subject.kind.value)
        except ValueError as exc:
            raise ValueError(_EVENT_OWNER_SUBJECT_REF_ERROR) from exc
        return cls(kind=kind, instance=subject.instance)


EventSubject = EventHomeRef | EventSubjectMarker
EventSubjectOwner = EventOwnerRef | EventSubjectOwnerMarker


def subject_token(subject: EventSubject) -> str:
    if isinstance(subject, EventHomeRef):
        return subject.to_token()
    return subject.value


def _subject_from_token(token: str) -> EventSubject:
    try:
        return EventSubjectMarker(token)
    except ValueError:
        return EventHomeRef.from_token(token)


def _subject_owner_token(owner: EventSubjectOwner) -> str:
    if isinstance(owner, EventOwnerRef):
        return owner.to_token()
    return owner.value


def _subject_owner_from_token(token: str) -> EventSubjectOwner:
    try:
        return EventSubjectOwnerMarker(token)
    except ValueError:
        return EventOwnerRef.from_token(token)


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
    """Event payload with required subject and composed origin facts for stream consumers."""

    model_config = ConfigDict(extra="allow")

    # Identity
    event: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = SCHEMA_VERSION
    source: str
    originating_computer: str | None = None
    originating_session_id: str | None = None
    origin_home: EventHomeRef | None = None
    subject: EventSubject
    subject_owner: EventSubjectOwner = EventSubjectOwnerMarker.NONE
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
    human_action: HumanActionIntent | None = None
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
            _ORIGIN_SESSION_STREAM_KEY: self.originating_session_id or "",
            _ORIGIN_HOME_STREAM_KEY: self.origin_home.to_token() if self.origin_home else "",
            _SUBJECT_STREAM_KEY: subject_token(self.subject),
            _SUBJECT_OWNER_STREAM_KEY: _subject_owner_token(self.subject_owner),
            "timestamp": cast(str, dumped["timestamp"]),
            "idempotency_key": self.idempotency_key or "",
            "level": str(int(self.level)),
            "domain": self.domain,
            "entity": self.entity or "",
            "description": self.description,
            "visibility": self.visibility.value,
            "payload": json.dumps(self.payload),
            "actions": json.dumps({k: v.model_dump() for k, v in self.actions.items()}) if self.actions else "",
            _HUMAN_ACTION_STREAM_KEY: self.human_action.model_dump_json() if self.human_action else "",
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
        human_action_raw = d.get(_HUMAN_ACTION_STREAM_KEY, "")
        human_action = HumanActionIntent.model_validate_json(human_action_raw) if human_action_raw else None
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
            originating_session_id=d.get(_ORIGIN_SESSION_STREAM_KEY) or None,
            origin_home=EventHomeRef.from_token(d[_ORIGIN_HOME_STREAM_KEY]) if d.get(_ORIGIN_HOME_STREAM_KEY) else None,
            subject=_subject_from_token(d.get(_SUBJECT_STREAM_KEY, EventSubjectMarker.UNKNOWN.value)),
            subject_owner=_subject_owner_from_token(
                d.get(_SUBJECT_OWNER_STREAM_KEY, EventSubjectOwnerMarker.NONE.value)
            ),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            idempotency_key=d.get("idempotency_key") or None,
            level=EventLevel(int(d["level"])),
            domain=d.get("domain", ""),
            entity=d.get("entity") or None,
            description=d.get("description", ""),
            visibility=EventVisibility(d.get("visibility", "local")),
            payload=payload,
            actions=actions,
            human_action=human_action,
            terminal_when=d.get("terminal_when") or None,
            resolution_shape=resolution_shape,
            **extra,
        )


EventEnvelope.model_rebuild()
