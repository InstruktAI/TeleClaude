"""Platform event wire codec: the stream entry a producer writes and every reader decodes.

A stream entry carries the event's own attributes under keys that cannot collide
with the earlier envelope (`ce_*`, plus `event_id`, `timestamp` and `payload`,
whose meaning is identical), and beside them every key an older computer reads
today, in the shape it reads them, with the type's earlier name in `event`. A
computer running this release decodes either shape: an entry with `ce_type` from
its own keys, an older entry by upcasting its legacy keys. Readers ignore keys
they do not know.

The legacy facts an older computer's notification path reads (level, domain,
producer label, entity, description, visibility, human action, idempotency key)
travel beside the received event in process and never become part of it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from teleclaude.core.models import HumanActionIntent, JsonDict
from teleclaude.events.envelope import (
    EventHome,
    EventHomeMarker,
    EventHomeOwner,
    EventLevel,
    EventVisibility,
    ReceivedEvent,
    home_from_token,
    home_owner_from_token,
    home_owner_token,
    home_token,
    occurrence_id,
)
from teleclaude.events.references import EventRef, ReferenceKind
from teleclaude.events.renames import current_type_name, earlier_type_name

#: Wire generation of the platform stream; bumped when keys are added.
PLATFORM_STREAM_VERSION: int = 6

_KEY_TYPE = "ce_type"
_KEY_SOURCE = "ce_source"
_KEY_SUBJECT = "ce_subject"
_KEY_HOME = "ce_home"
_KEY_HOME_OWNER = "ce_home_owner"
_KEY_RELATED = "ce_related"
_KEY_CAUSATIONID = "ce_causationid"
_KEY_ID = "event_id"
_KEY_TIME = "timestamp"
_KEY_DATA = "payload"
_KEY_VERSION = "version"
_KEY_EVENT = "event"
_KEY_PRODUCER = "source"
_KEY_ORIGINATING_COMPUTER = "originating_computer"
_KEY_ORIGINATING_SESSION = "originating_session_id"
_KEY_ORIGIN_HOME = "origin_home"
_KEY_LEGACY_HOME = "subject"
_KEY_LEGACY_HOME_OWNER = "subject_owner"
_KEY_IDEMPOTENCY = "idempotency_key"
_KEY_LEVEL = "level"
_KEY_DOMAIN = "domain"
_KEY_ENTITY = "entity"
_KEY_DESCRIPTION = "description"
_KEY_VISIBILITY = "visibility"
_KEY_ACTIONS = "actions"
_KEY_HUMAN_ACTION = "human_action"
_KEY_TERMINAL_WHEN = "terminal_when"
_KEY_RESOLUTION_SHAPE = "resolution_shape"
_KEY_LEGACY_ID_EXTRA = "_extra"

_DEFAULT_HOME_OWNER = "none"
_EMPTY = ""
_ENTRY_FIELD = "{key}={value}"

#: Data fields an older computer's notification path reads from the payload, by current type name.
#: They are written into the legacy payload beside the data and removed again on decode.
LEGACY_ONLY_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "teleclaude.job.run.succeeded": frozenset({"actionable"}),
    "teleclaude.job.run.failed": frozenset({"actionable"}),
    "teleclaude.job.run.stalled": frozenset({"actionable"}),
}


class LegacyFacts(BaseModel):
    """The notification-path facts older computers read, stated by the producer at emission.

    They are not event facts: no typed event, received attribute or declaration
    carries them. Only an older computer's notification projector reads them, and they leave the
    wire once the fleet answers that no live computer does.
    """

    model_config = ConfigDict(frozen=True)

    producer: str
    level: EventLevel
    domain: str = ""
    entity: str | None = None
    description: str = ""
    visibility: EventVisibility = EventVisibility.LOCAL
    human_action: HumanActionIntent | None = None
    idempotency_key: str | None = None
    #: Legacy-only data fields (see `LEGACY_ONLY_PAYLOAD_FIELDS`) the producer states beside the data.
    payload_extras: JsonDict = Field(default_factory=dict)


class StreamEvent(ReceivedEvent):
    """A decoded stream entry in process: the received event and the legacy facts that ride beside it."""

    legacy: LegacyFacts


def _legacy_payload_fields(event_type: str) -> frozenset[str]:
    return LEGACY_ONLY_PAYLOAD_FIELDS.get(event_type, frozenset())


def encode(event: ReceivedEvent, legacy: LegacyFacts, *, omit_notification_facts: bool = False) -> dict[str, str]:
    """Serialize one event for the platform stream: its attributes, and every key older computers read.

    With `omit_notification_facts` the keys only an older computer's notification path reads — the
    visibility, the human action and the legacy-only data fields — are left out; readers default them.
    """
    session_ids = [reference.identity for reference in event.related if reference.is_kind(ReferenceKind.SESSION)]
    entry = {
        _KEY_TYPE: event.type,
        _KEY_SOURCE: event.source,
        _KEY_SUBJECT: event.subject.to_token() if event.subject is not None else _EMPTY,
        _KEY_HOME: home_token(event.home),
        _KEY_HOME_OWNER: home_owner_token(event.home_owner),
        _KEY_RELATED: json.dumps([reference.to_token() for reference in event.related]),
        _KEY_CAUSATIONID: event.causationid or _EMPTY,
        _KEY_ID: event.id,
        _KEY_TIME: event.time.isoformat(),
        _KEY_DATA: json.dumps(event.data if omit_notification_facts else {**event.data, **legacy.payload_extras}),
        _KEY_VERSION: str(PLATFORM_STREAM_VERSION),
        _KEY_EVENT: earlier_type_name(event.type),
        _KEY_PRODUCER: legacy.producer,
        _KEY_ORIGINATING_COMPUTER: event.source,
        _KEY_ORIGINATING_SESSION: session_ids[0] if session_ids else _EMPTY,
        _KEY_ORIGIN_HOME: _EMPTY,
        _KEY_LEGACY_HOME: home_token(event.home),
        _KEY_LEGACY_HOME_OWNER: home_owner_token(event.home_owner),
        _KEY_IDEMPOTENCY: legacy.idempotency_key or _EMPTY,
        _KEY_LEVEL: str(int(legacy.level)),
        _KEY_DOMAIN: legacy.domain,
        _KEY_ENTITY: legacy.entity or _EMPTY,
        _KEY_DESCRIPTION: legacy.description,
        _KEY_VISIBILITY: legacy.visibility.value,
        _KEY_ACTIONS: _EMPTY,
        _KEY_HUMAN_ACTION: legacy.human_action.model_dump_json() if legacy.human_action else _EMPTY,
        _KEY_TERMINAL_WHEN: _EMPTY,
        _KEY_RESOLUTION_SHAPE: _EMPTY,
    }
    if omit_notification_facts:
        del entry[_KEY_VISIBILITY]
        del entry[_KEY_HUMAN_ACTION]
    return entry


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _event_id(entry: dict[str, str], entry_id: str) -> str:
    """Return the entry's event id; a pre-fix entry carried it only inside its extras, or not at all.

    An entry that states none gets an id derived from its stream entry id and its own content, so
    every decode of the same entry (a retry of a pending one) yields the same id and distinct
    entries never share one.
    """
    if entry.get(_KEY_ID):
        return entry[_KEY_ID]
    extra_raw = entry.get(_KEY_LEGACY_ID_EXTRA, _EMPTY)
    legacy_id = json.loads(extra_raw).get(_KEY_ID) if extra_raw else None
    if isinstance(legacy_id, str) and legacy_id:
        return legacy_id
    return occurrence_id(entry_id, *(_ENTRY_FIELD.format(key=key, value=value) for key, value in sorted(entry.items())))


@dataclass(frozen=True)
class _Attributes:
    """The attributes an entry states about its event, read from its own keys or upcast from legacy keys."""

    source: str
    subject: EventRef | None
    home: EventHome
    home_owner: EventHomeOwner
    related: tuple[EventRef, ...]
    causationid: str | None


def _attributes(entry: dict[str, str]) -> _Attributes:
    """Read the event's attributes from a new-shape entry's own keys, or upcast an older entry's legacy keys."""
    if _KEY_TYPE in entry:
        return _Attributes(
            source=entry[_KEY_SOURCE],
            subject=EventRef.from_token(entry[_KEY_SUBJECT]) if entry.get(_KEY_SUBJECT) else None,
            home=home_from_token(entry[_KEY_HOME]),
            home_owner=home_owner_from_token(entry.get(_KEY_HOME_OWNER, _DEFAULT_HOME_OWNER)),
            related=tuple(EventRef.from_token(token) for token in json.loads(entry.get(_KEY_RELATED) or "[]")),
            causationid=entry.get(_KEY_CAUSATIONID) or None,
        )
    return _Attributes(
        source=entry.get(_KEY_ORIGINATING_COMPUTER) or _EMPTY,
        subject=None,
        home=home_from_token(entry.get(_KEY_LEGACY_HOME, EventHomeMarker.UNKNOWN.value)),
        home_owner=home_owner_from_token(entry.get(_KEY_LEGACY_HOME_OWNER, _DEFAULT_HOME_OWNER)),
        related=(),
        causationid=None,
    )


type StreamEntry = dict[bytes, bytes] | dict[str, str]


@dataclass(frozen=True)
class EntryCodec[DecodedT: BaseModel]:
    """How a stream's processor decodes one entry and names the event it carries."""

    #: Decode one entry, given the stream's own id for it.
    decode: Callable[[StreamEntry, str], DecodedT]
    event_id: Callable[[DecodedT], str]


def decode(data: StreamEntry, entry_id: str = _EMPTY) -> StreamEvent:
    """Decode one stream entry, new shape or older, into the received event and its legacy facts."""
    entry = {_text(key): _text(value) for key, value in data.items()}
    event_type = entry[_KEY_TYPE] if _KEY_TYPE in entry else current_type_name(entry[_KEY_EVENT])
    payload: JsonDict = json.loads(entry[_KEY_DATA]) if entry.get(_KEY_DATA) else {}
    extras = {name: payload.pop(name) for name in _legacy_payload_fields(event_type) if name in payload}
    human_action_raw = entry.get(_KEY_HUMAN_ACTION, _EMPTY)
    legacy = LegacyFacts(
        producer=entry[_KEY_PRODUCER],
        level=EventLevel(int(entry[_KEY_LEVEL])),
        domain=entry.get(_KEY_DOMAIN, _EMPTY),
        entity=entry.get(_KEY_ENTITY) or None,
        description=entry.get(_KEY_DESCRIPTION, _EMPTY),
        visibility=EventVisibility(entry.get(_KEY_VISIBILITY, EventVisibility.LOCAL.value)),
        human_action=HumanActionIntent.model_validate_json(human_action_raw) if human_action_raw else None,
        idempotency_key=entry.get(_KEY_IDEMPOTENCY) or None,
        payload_extras=extras,
    )
    attributes = _attributes(entry)
    return StreamEvent(
        id=_event_id(entry, entry_id),
        type=event_type,
        source=attributes.source,
        subject=attributes.subject,
        time=datetime.fromisoformat(entry[_KEY_TIME]),
        data=payload,
        home=attributes.home,
        home_owner=attributes.home_owner,
        related=attributes.related,
        causationid=attributes.causationid,
        legacy=legacy,
    )


#: The platform stream's codec.
PLATFORM_ENTRY_CODEC = EntryCodec(decode=decode, event_id=lambda event: event.id)
