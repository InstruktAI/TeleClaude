"""Event catalog — the typed declarations producers construct, and the catalog generated from them.

Every event type is declared once, as a `PlatformEvent` subclass: its name,
version, description, the kind of thing its subject names, the home kinds its
home can take, the typed data it carries, and the kinds its related references
name. A platform type that reports the state of a thing declares its family and
state instead of a written-out name. The catalog behind `telec events list` and
`telec events schema` is generated from these classes, and generation refuses a
declaration set that breaks the lifecycle-state convention.
"""

from __future__ import annotations

import types
from enum import StrEnum
from importlib import import_module
from typing import Any, ClassVar, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator

from teleclaude.events.envelope import EventHome, EventHomeKind, EventHomeMarker, EventHomeRef
from teleclaude.events.references import EventRef, Reference, ReferenceKind, TypedRef

PLATFORM_OWNER = "teleclaude"
_TYPE_SEGMENT_SEPARATOR = "."
_JSON_ARRAY_ORIGINS: frozenset[type] = frozenset({list, tuple, set, frozenset})
_REFUSAL_SEPARATOR = "; "
_HOME_KIND_NOT_DECLARED = "{type_name} cannot take a {kind} home"
_HOME_NOT_DECLARED = "{type_name} belongs to no registered home"
_RELATED_KIND_NOT_DECLARED = "{type_name} cannot relate a {kind}"
_SUBJECT_UNTYPED = "{class_name} does not type its subject reference"
_DATA_UNTYPED = "{class_name} does not type its data"
_DUPLICATE_DECLARATION = "{name}: declared more than once"
_NAME_AND_STATE = "{class_name}: declares both a written-out name and a state"
_NAMELESS_DECLARATION = "{class_name}: declares no name or description"
_DOMAIN_STATE = "{name}: a domain type declares a state"
_UNDECLARED_STATE_SEGMENT = "{name}: reports no state but ends in a state segment"
_FAILING_WITHOUT_OK = "{family}: declares a failing state and no ok state"
_FAMILY_SUBJECT_KINDS = "{family}: its states differ in subject kind"


class StateStanding(StrEnum):
    """Whether a lifecycle state reports a thing failing or ok."""

    FAILING = "failing"
    OK = "ok"


class LifecycleState(StrEnum):
    """Closed vocabulary of lifecycle-state segments a platform type's name can end in."""

    FAILED = "failed"
    STALLED = "stalled"
    DEGRADED = "degraded"
    DETECTED = "detected"
    SUCCEEDED = "succeeded"
    RECOVERED = "recovered"
    SUBSIDED = "subsided"


STATE_STANDING: dict[LifecycleState, StateStanding] = {
    LifecycleState.FAILED: StateStanding.FAILING,
    LifecycleState.STALLED: StateStanding.FAILING,
    LifecycleState.DEGRADED: StateStanding.FAILING,
    LifecycleState.DETECTED: StateStanding.FAILING,
    LifecycleState.SUCCEEDED: StateStanding.OK,
    LifecycleState.RECOVERED: StateStanding.OK,
    LifecycleState.SUBSIDED: StateStanding.OK,
}


class DataValueKind(StrEnum):
    """JSON value kinds declared for event data fields."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    ANY = "any"


class DataField(BaseModel):
    """One declared event data field and its wire value shape."""

    name: str
    kind: DataValueKind
    nullable: bool


class StateDeclaration(BaseModel):
    """The lifecycle state a platform type reports, under its family."""

    family: str
    state: LifecycleState
    standing: StateStanding


class EventDeclaration(BaseModel):
    """What the catalog shows for one type: generated from the class producers construct."""

    name: str
    version: int
    description: str
    #: The one kind of thing the subject names; None when the subject can be a thing of any kind.
    subject_kind: ReferenceKind | None
    home_kinds: list[EventHomeKind]
    data_fields: list[DataField]
    related_kinds: list[ReferenceKind]
    state: StateDeclaration | None = None


class CatalogConventionError(ValueError):
    """The declared set breaks a catalog rule; the message names the offending declarations."""


class EventData(BaseModel):
    """Base of a declared type's data: facts only, strictly typed, nothing undeclared."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PlatformEvent[SubjectT: Reference, DataT: EventData](BaseModel):
    """Base of every declared event type; producers construct subclasses and nothing else.

    A subclass states its name (or family and state), version, description,
    home kinds and related kinds as class-level declarations, and its subject
    reference type and data model as the type arguments. The producer supplies
    the subject, the home and the data; the emission boundary adds source, time,
    the caller session and the project owner. An event carries facts only:
    no notification rule, action, audience or routing scope.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    NAME: ClassVar[str] = ""
    FAMILY: ClassVar[str] = ""
    STATE: ClassVar[LifecycleState | None] = None
    VERSION: ClassVar[int] = 1
    DESCRIPTION: ClassVar[str] = ""
    #: Home kinds the event's home can take; empty means the type belongs to no registered home.
    HOME_KINDS: ClassVar[tuple[EventHomeKind, ...]] = ()
    RELATED_KINDS: ClassVar[tuple[ReferenceKind, ...]] = (ReferenceKind.SESSION,)

    subject: SubjectT
    home: EventHome
    data: DataT
    related: tuple[Reference, ...] = ()
    causationid: str | None = None
    id: str | None = None

    @classmethod
    def type_name(cls) -> str:
        """Return the declared type name: written out, or composed from family and state."""
        if cls.STATE is None:
            return cls.NAME
        return _TYPE_SEGMENT_SEPARATOR.join((cls.FAMILY, cls.STATE.value))

    @model_validator(mode="after")
    def _home_matches_declaration(self) -> PlatformEvent[SubjectT, DataT]:
        """A home must be one the declaration allows; a type without home kinds has none."""
        if isinstance(self.home, EventHomeRef):
            if self.home.kind not in self.HOME_KINDS:
                raise ValueError(_HOME_KIND_NOT_DECLARED.format(type_name=self.type_name(), kind=self.home.kind.value))
        elif not self.HOME_KINDS and self.home is not EventHomeMarker.NONE:
            raise ValueError(_HOME_NOT_DECLARED.format(type_name=self.type_name()))
        return self

    @model_validator(mode="after")
    def _related_matches_declaration(self) -> PlatformEvent[SubjectT, DataT]:
        """Related references must name kinds the declaration allows."""
        allowed = {kind.value for kind in self.RELATED_KINDS}
        for reference in self.related:
            kind = reference.to_ref().kind
            if kind not in allowed:
                raise ValueError(_RELATED_KIND_NOT_DECLARED.format(type_name=self.type_name(), kind=kind))
        return self


def _is_platform_type(name: str) -> bool:
    return name.split(_TYPE_SEGMENT_SEPARATOR, 1)[0] == PLATFORM_OWNER


def _last_segment(name: str) -> str:
    return name.rsplit(_TYPE_SEGMENT_SEPARATOR, 1)[-1]


def _value_kind(annotation: object) -> DataValueKind:
    """Map a data field's annotation to the JSON value kind the catalog shows."""
    origin = get_origin(annotation) or annotation
    if origin is bool:
        return DataValueKind.BOOLEAN
    if origin is int:
        return DataValueKind.INTEGER
    if origin is float:
        return DataValueKind.NUMBER
    if origin is str:
        return DataValueKind.STRING
    if origin is dict:
        return DataValueKind.OBJECT
    if origin in _JSON_ARRAY_ORIGINS:
        return DataValueKind.ARRAY
    return DataValueKind.ANY


def _is_union(annotation: object) -> bool:
    return get_origin(annotation) in (Union, types.UnionType)


def _data_field(name: str, annotation: object) -> DataField:
    """Describe one data field: its kind, and whether null is allowed."""
    if _is_union(annotation):
        members = get_args(annotation)
        nullable = type(None) in members
        present = [member for member in members if member is not type(None)]
        kind = _value_kind(present[0]) if len(present) == 1 else DataValueKind.ANY
        return DataField(name=name, kind=kind, nullable=nullable)
    return DataField(name=name, kind=_value_kind(annotation), nullable=False)


type DeclaredEvent = type[PlatformEvent[Any, Any]]


def _annotation_of(event_class: DeclaredEvent, field: str) -> object:
    return event_class.model_fields[field].annotation


def _subject_kind(event_class: DeclaredEvent) -> ReferenceKind | None:
    """Return the one kind a typed subject names, or None for a subject of any kind."""
    subject_type = _annotation_of(event_class, "subject")
    if subject_type is EventRef:
        return None
    if isinstance(subject_type, type) and issubclass(subject_type, TypedRef):
        return subject_type.KIND
    raise CatalogConventionError(_SUBJECT_UNTYPED.format(class_name=event_class.__name__))


def declaration_of(event_class: DeclaredEvent) -> EventDeclaration:
    """Generate the catalog declaration from the class producers construct."""
    data_type = _annotation_of(event_class, "data")
    if not (isinstance(data_type, type) and issubclass(data_type, EventData)):
        raise CatalogConventionError(_DATA_UNTYPED.format(class_name=event_class.__name__))
    state = None
    if event_class.STATE is not None:
        state = StateDeclaration(
            family=event_class.FAMILY,
            state=event_class.STATE,
            standing=STATE_STANDING[event_class.STATE],
        )
    return EventDeclaration(
        name=event_class.type_name(),
        version=event_class.VERSION,
        description=event_class.DESCRIPTION,
        subject_kind=_subject_kind(event_class),
        home_kinds=list(event_class.HOME_KINDS),
        data_fields=[_data_field(name, info.annotation) for name, info in data_type.model_fields.items()],
        related_kinds=list(event_class.RELATED_KINDS),
        state=state,
    )


def _refusals(declarations: list[EventDeclaration], classes: list[DeclaredEvent]) -> list[str]:
    """Return one message per way the declared set breaks the catalog rules."""
    refusals: list[str] = []
    seen: set[str] = set()
    for event_class, declaration in zip(classes, declarations, strict=True):
        name = declaration.name
        if name in seen:
            refusals.append(_DUPLICATE_DECLARATION.format(name=name))
        seen.add(name)
        if event_class.STATE is not None and event_class.NAME:
            refusals.append(_NAME_AND_STATE.format(class_name=event_class.__name__))
        if not name or not event_class.DESCRIPTION:
            refusals.append(_NAMELESS_DECLARATION.format(class_name=event_class.__name__))
        if declaration.state is not None and not _is_platform_type(name):
            refusals.append(_DOMAIN_STATE.format(name=name))
        if declaration.state is None and _is_platform_type(name):
            if _last_segment(name) in {state.value for state in LifecycleState}:
                refusals.append(_UNDECLARED_STATE_SEGMENT.format(name=name))
    families: dict[str, list[EventDeclaration]] = {}
    for declaration in declarations:
        if declaration.state is not None:
            families.setdefault(declaration.state.family, []).append(declaration)
    for family, members in sorted(families.items()):
        standings = {member.state.standing for member in members if member.state is not None}
        if StateStanding.FAILING in standings and StateStanding.OK not in standings:
            refusals.append(_FAILING_WITHOUT_OK.format(family=family))
        if len({member.subject_kind for member in members}) > 1:
            refusals.append(_FAMILY_SUBJECT_KINDS.format(family=family))
    return refusals


class EventCatalog:
    """The generated registry of declared event types, keyed by type name."""

    def __init__(self, classes: tuple[DeclaredEvent, ...]) -> None:
        declarations = [declaration_of(event_class) for event_class in classes]
        refusals = _refusals(declarations, list(classes))
        if refusals:
            raise CatalogConventionError(_REFUSAL_SEPARATOR.join(refusals))
        self._registry = {declaration.name: declaration for declaration in declarations}

    def get(self, event_type: str) -> EventDeclaration | None:
        """Return the declaration for a type name, if one is declared."""
        return self._registry.get(event_type)

    def list_all(self) -> list[EventDeclaration]:
        """Return all declarations sorted by type name."""
        return sorted(self._registry.values(), key=lambda declaration: declaration.name)


def build_default_catalog() -> EventCatalog:
    """Generate the catalog from every built-in declaration."""
    declared_events = import_module("teleclaude.events.schemas.registry").declared_events
    return EventCatalog(declared_events())
