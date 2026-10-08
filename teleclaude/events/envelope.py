"""Event model — the home vocabulary, the received platform event, and event levels and visibility.

A platform event as every reader sees it is a `ReceivedEvent`: id, type, source,
subject, time, data and the home extensions. Its wire form lives in
`teleclaude.events.wire`. The home vocabulary names whose an event is: a registered
project, person or company, none, or unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum, StrEnum
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef, SubjectSource
from teleclaude.core.models import JsonDict
from teleclaude.events.references import EventRef
from teleclaude.slug import validate_slug

_EVENT_HOME_KIND_TYPE_ERROR = "event home kind must be an EventHomeKind"
_EVENT_HOME_SUBJECT_REF_ERROR = "event homes must name registered project, person, or company subjects"
_EVENT_OWNER_KIND_TYPE_ERROR = "event owner kind must be an EventOwnerKind"
_OCCURRENCE_SEPARATOR = "\x1f"
_EVENT_OWNER_SUBJECT_REF_ERROR = "event owners must name registered company or person subjects"


class EventHomeMarker(StrEnum):
    """Explicit home states that are not registered homes: none is a claim, unknown makes none."""

    NONE = "none"
    UNKNOWN = "unknown"


class EventHomeOwnerMarker(StrEnum):
    """Explicit project-owner states that are not registry references."""

    NONE = "none"
    OWNERLESS = "ownerless"
    UNRESOLVED = "unresolved"


class EventHomeKind(StrEnum):
    """Configuration homes an event can belong to."""

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


EventHome = EventHomeRef | EventHomeMarker
EventHomeOwner = EventOwnerRef | EventHomeOwnerMarker


def home_token(home: EventHome) -> str:
    if isinstance(home, EventHomeRef):
        return home.to_token()
    return home.value


def home_from_token(token: str) -> EventHome:
    try:
        return EventHomeMarker(token)
    except ValueError:
        return EventHomeRef.from_token(token)


def home_owner_token(owner: EventHomeOwner) -> str:
    if isinstance(owner, EventOwnerRef):
        return owner.to_token()
    return owner.value


def home_owner_from_token(token: str) -> EventHomeOwner:
    try:
        return EventHomeOwnerMarker(token)
    except ValueError:
        return EventOwnerRef.from_token(token)


def occurrence_id(*identity: str) -> str:
    """Return the event id of one occurrence a producer may report more than once.

    The id derives from the occurrence's own identity, so the same occurrence
    emitted a second time (such as after an interrupted publish) carries the same
    id and two distinct occurrences never share one.
    """
    return str(uuid5(NAMESPACE_URL, _OCCURRENCE_SEPARATOR.join(identity)))


class ReceivedEvent(BaseModel):
    """A platform event as every reader sees it: its attributes, exactly as the producer stated them.

    The id, type, source, time and home are on every event. The subject, related
    references and causation id are absent on an event an older computer emitted
    and on events that have none; absent states nothing and is never unknown.
    The data is opaque to every reader that has not matched the type.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    source: str
    subject: EventRef | None = None
    time: datetime
    data: JsonDict = Field(default_factory=dict)
    home: EventHome
    home_owner: EventHomeOwner = EventHomeOwnerMarker.NONE
    related: tuple[EventRef, ...] = ()
    causationid: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        """Reject empty event identities at the model boundary."""
        if not value.strip():
            raise ValueError("event id must be a non-empty string")
        return value


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
