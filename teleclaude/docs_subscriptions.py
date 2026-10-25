"""Publishes the platform's declared procedure event subscriptions, their reach, and the index identity."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from teleclaude.events.type_pattern import TypePattern
from teleclaude.paths import GLOBAL_DOCS_DIR
from teleclaude.snippet_scope import SnippetScope

_INDEX_FILE_NAME = "index.yaml"
_COMPANY_SOURCE_PREFIX = "company:"
_PERSON_SOURCE_PREFIX = "person:"
_PROCEDURE_TYPE = "procedure"
_UTF8 = "utf-8"
_UNREADABLE_TIER_ERROR = (
    "Unreadable tier {scope!r} for subscribed procedure {procedure_id!r}. "
    "A subscription published where no tier routes it would otherwise publish as global "
    "(matching every home) — refusing rather than widening reach."
)
_MALFORMED_SOURCE_PROJECT_ERROR = (
    "Malformed {scope}-tier source_project for {procedure_id!r}: {source_project!r}. "
    "A tier-scoped subscription with no resolvable home would otherwise publish as "
    "global (matching every home) — refusing rather than widening reach."
)
_EMPTY_HOME_SLUG_ERROR = "Empty home slug in source_project for {procedure_id!r}: {source_project!r}"
_UNREADABLE_HOME_KIND_ERROR = "Unreadable subscription_home {home!r} for subscribed procedure {procedure_id!r}"
_UNREADABLE_IDENTITY_ERROR = (
    "Unreadable subscription_identity {identity!r} for subscribed procedure {procedure_id!r} — "
    "refusing rather than widening which agent answers its events."
)
_UNREADABLE_ATTENDANCE_ERROR = (
    "Unreadable subscription_attendance {attendance!r} for subscribed procedure {procedure_id!r} — "
    "refusing rather than widening which agents appear where people look at sessions."
)
_TIER_KIND_MISMATCH_ERROR = (
    "Procedure {procedure_id!r} is published in a {tier} tier but answers {answered} events — "
    "refusing rather than widening reach."
)
_UNREADABLE_DELIVERY_SETTINGS_ERROR = "Unreadable event delivery settings for subscribed procedure {procedure_id!r}"
_MALFORMED_INDEX_SNIPPETS_ERROR = "The published index carries a {kind} where its snippets list belongs"


class IndexKey(StrEnum):
    """The keys of the published merged index this reader consumes."""

    SNIPPETS = "snippets"
    ID = "id"
    TYPE = "type"
    SCOPE = "scope"
    SOURCE_PROJECT = "source_project"
    PATH = "path"
    ACTIVATION_TRIGGER = "activation_trigger"
    DELIVERED_BY = "delivered_by"
    SUPERSEDED_BY = "superseded_by"
    SUBSCRIPTIONS = "subscriptions"
    SUBSCRIPTION_HOME = "subscription_home"
    SUBSCRIPTION_IDENTITY = "subscription_identity"
    SUBSCRIPTION_ATTENDANCE = "subscription_attendance"
    EVENT_DELIVERY = "event_delivery"
    INTERRUPTIBLE = "interruptible"


class EventDeliveryMode(StrEnum):
    SEQUENTIAL = "sequential"
    BATCHED = "batched"


@dataclass(frozen=True)
class ProcedureDeliverySettings:
    event_delivery: EventDeliveryMode
    interruptible: bool


class DeliveryDeclarationError(ValueError):
    def __init__(self, field: IndexKey, *, misplaced: bool = False) -> None:
        self.field = field
        self.misplaced = misplaced
        super().__init__(field.value)


def resolve_delivery_settings(metadata: Mapping[str, object]) -> ProcedureDeliverySettings | None:
    """Resolve one subscribed procedure's delivery settings or reject its declaration."""
    has_delivery_field = IndexKey.EVENT_DELIVERY in metadata or IndexKey.INTERRUPTIBLE in metadata
    if metadata.get(IndexKey.SUBSCRIPTIONS) is None:
        if has_delivery_field:
            raise DeliveryDeclarationError(
                IndexKey.EVENT_DELIVERY if IndexKey.EVENT_DELIVERY in metadata else IndexKey.INTERRUPTIBLE,
                misplaced=True,
            )
        return None

    raw_mode = metadata.get(IndexKey.EVENT_DELIVERY, EventDeliveryMode.SEQUENTIAL)
    if not isinstance(raw_mode, str):
        raise DeliveryDeclarationError(IndexKey.EVENT_DELIVERY)
    try:
        event_delivery = EventDeliveryMode(raw_mode)
    except (TypeError, ValueError) as exc:
        raise DeliveryDeclarationError(IndexKey.EVENT_DELIVERY) from exc

    raw_interruptible = metadata.get(IndexKey.INTERRUPTIBLE, False)
    if not isinstance(raw_interruptible, bool):
        raise DeliveryDeclarationError(IndexKey.INTERRUPTIBLE)
    return ProcedureDeliverySettings(event_delivery=event_delivery, interruptible=raw_interruptible)


class SubscriptionHomeKind(StrEnum):
    """The one kind of home a subscribed procedure answers; ``platform`` answers events of no home."""

    COMPANY = "company"
    PERSON = "person"
    PROJECT = "project"
    PLATFORM = "platform"


class SubscriptionIdentity(StrEnum):
    """Which agent answers each activating event: one per home, or one per event subject within the home."""

    HOME = "home"
    SUBJECT = "subject"


class SubscriptionAttendance(StrEnum):
    """Whether people look at a procedure's agents: ``unattended`` ones stay out of session listings and Discord."""

    ATTENDED = "attended"
    UNATTENDED = "unattended"


#: The home kind a procedure published in a home's own tier must answer, and the token prefix naming that home.
_TIER_HOME: dict[SnippetScope, tuple[SubscriptionHomeKind, str]] = {
    SnippetScope.COMPANY: (SubscriptionHomeKind.COMPANY, _COMPANY_SOURCE_PREFIX),
    SnippetScope.PERSON: (SubscriptionHomeKind.PERSON, _PERSON_SOURCE_PREFIX),
}


@dataclass(frozen=True)
class IndexFileIdentity:
    """What identifies one version of the deployed index file without reading it.

    Publication replaces the file atomically, so a replaced file differs in at
    least its inode or modification time.
    """

    inode: int
    modified_ns: int
    size: int


@dataclass(frozen=True)
class SubscriptionEntry:
    """One live procedure's declared patterns, the home kind it answers, the reach of its tier and its agent.

    ``home_slug`` is the one home the publishing tier limits the procedure to,
    or ``None`` for a global procedure, which answers every home of its kind.
    ``identity`` is which agent answers each activating event; ``attendance``
    is whether people look at that agent's session.
    """

    procedure_id: str
    patterns: tuple[TypePattern, ...]
    home_kind: SubscriptionHomeKind
    home_slug: str | None
    identity: SubscriptionIdentity
    attendance: SubscriptionAttendance
    delivery: ProcedureDeliverySettings

    def matches_type(self, event_type: str) -> bool:
        """Whether any declared pattern selects the event type."""
        return any(pattern.matches(event_type) for pattern in self.patterns)

    def reaches(self, home_kind: SubscriptionHomeKind, home_slug: str | None) -> bool:
        """Whether this procedure answers the home: its kind, within its tier's reach."""
        if home_kind is not self.home_kind:
            return False
        return self.home_slug is None or self.home_slug == home_slug


@dataclass(frozen=True)
class SubscriptionPublication:
    """The published subscription set with the index file identity and digest it was read from."""

    identity: IndexFileIdentity
    digest: str
    entries: tuple[SubscriptionEntry, ...]


def published_index_path(docs_dir: Path = GLOBAL_DOCS_DIR) -> Path:
    """Where the merged index is deployed under a docs directory (the runtime home's by default)."""
    return docs_dir / _INDEX_FILE_NAME


def published_index_identity() -> IndexFileIdentity:
    """The identity of the deployed merged index file as it is now."""
    stat = published_index_path().stat()
    return IndexFileIdentity(inode=stat.st_ino, modified_ns=stat.st_mtime_ns, size=stat.st_size)


def tier_source_project(scope: SnippetScope, slug: str) -> str:
    """The ``source_project`` token the merged index records for one company or person tier home's entries."""
    return f"{_TIER_HOME[scope][1]}{slug}"


def _tier_reach(procedure_id: str, entry: Mapping[str, object]) -> tuple[SubscriptionHomeKind | None, str | None]:
    """The home kind a tier fixes and the one home slug it limits the procedure to; global fixes neither."""
    try:
        scope = SnippetScope(str(entry.get(IndexKey.SCOPE)))
    except ValueError:
        scope = None
    if scope is SnippetScope.GLOBAL:
        return None, None
    tier_home = _TIER_HOME.get(scope) if scope is not None else None
    if scope is None or tier_home is None:
        raise ValueError(_UNREADABLE_TIER_ERROR.format(scope=entry.get(IndexKey.SCOPE), procedure_id=procedure_id))
    tier_home_kind, prefix = tier_home
    source_project = entry.get(IndexKey.SOURCE_PROJECT)
    if not isinstance(source_project, str) or not source_project.startswith(prefix):
        raise ValueError(
            _MALFORMED_SOURCE_PROJECT_ERROR.format(
                scope=scope.value, procedure_id=procedure_id, source_project=source_project
            )
        )
    slug = source_project.removeprefix(prefix)
    if not slug:
        raise ValueError(_EMPTY_HOME_SLUG_ERROR.format(procedure_id=procedure_id, source_project=source_project))
    return tier_home_kind, slug


def _subscription_entry(
    procedure_id: str, entry: Mapping[str, object], subscriptions: list[object]
) -> SubscriptionEntry:
    delivery = resolve_delivery_settings({**entry, IndexKey.SUBSCRIPTIONS: subscriptions})
    if delivery is None:
        raise ValueError(_UNREADABLE_DELIVERY_SETTINGS_ERROR.format(procedure_id=procedure_id))
    try:
        home_kind = SubscriptionHomeKind(str(entry.get(IndexKey.SUBSCRIPTION_HOME)))
    except ValueError as exc:
        raise ValueError(
            _UNREADABLE_HOME_KIND_ERROR.format(home=entry.get(IndexKey.SUBSCRIPTION_HOME), procedure_id=procedure_id)
        ) from exc
    raw_identity = entry.get(IndexKey.SUBSCRIPTION_IDENTITY, SubscriptionIdentity.HOME)
    try:
        identity = SubscriptionIdentity(str(raw_identity))
    except ValueError as exc:
        raise ValueError(_UNREADABLE_IDENTITY_ERROR.format(identity=raw_identity, procedure_id=procedure_id)) from exc
    raw_attendance = entry.get(IndexKey.SUBSCRIPTION_ATTENDANCE, SubscriptionAttendance.ATTENDED)
    try:
        attendance = SubscriptionAttendance(str(raw_attendance))
    except ValueError as exc:
        raise ValueError(
            _UNREADABLE_ATTENDANCE_ERROR.format(attendance=raw_attendance, procedure_id=procedure_id)
        ) from exc
    tier_home_kind, home_slug = _tier_reach(procedure_id, entry)
    if tier_home_kind is not None and home_kind is not tier_home_kind:
        raise ValueError(
            _TIER_KIND_MISMATCH_ERROR.format(
                procedure_id=procedure_id, tier=tier_home_kind.value, answered=home_kind.value
            )
        )
    return SubscriptionEntry(
        procedure_id=procedure_id,
        patterns=tuple(TypePattern(str(pattern)) for pattern in subscriptions),
        home_kind=home_kind,
        home_slug=home_slug,
        identity=identity,
        attendance=attendance,
        delivery=delivery,
    )


def parse_published_snippets(raw: bytes) -> list[Mapping[str, object]]:
    """The snippet entries of the merged index bytes, pending entries included.

    Raises ``yaml.YAMLError`` or ``ValueError`` when the bytes are not a readable
    index. An index document that is not a mapping carries no entries.
    """
    payload = yaml.safe_load(raw.decode(_UTF8)) or {}
    snippets = payload.get(IndexKey.SNIPPETS, []) if isinstance(payload, dict) else []
    if not isinstance(snippets, list):
        raise ValueError(_MALFORMED_INDEX_SNIPPETS_ERROR.format(kind=type(snippets).__name__))
    return [entry for entry in snippets if isinstance(entry, dict)]


def read_published_snippets(docs_dir: Path = GLOBAL_DOCS_DIR) -> list[Mapping[str, object]]:
    """The snippet entries of the merged index deployed under a docs directory. A missing index raises ``FileNotFoundError``."""
    return parse_published_snippets(published_index_path(docs_dir).read_bytes())


def published_procedure_subscriptions() -> SubscriptionPublication:
    """Read every live procedure's declared subscriptions from the deployed merged index.

    Reads the one file publication already replaces atomically, so its bytes
    are the version a caller re-derives from on an identity change. Each entry
    carries its parsed type patterns, the home kind it answers, its agent
    identity (``home`` when undeclared), its attendance (``attended`` when
    undeclared), and its tier's reach: a ``scope: global`` entry answers every home of its kind, a
    ``scope: company`` or ``scope: person`` entry the one home its
    ``source_project`` token names. An entry whose tier, patterns, home kind,
    agent identity or attendance cannot be read raises. Pending (``delivered_by``) entries are excluded.
    """
    identity = published_index_identity()
    raw = published_index_path().read_bytes()
    digest = hashlib.sha256(raw).hexdigest()

    entries: list[SubscriptionEntry] = []
    for entry in parse_published_snippets(raw):
        if entry.get(IndexKey.TYPE) != _PROCEDURE_TYPE or entry.get(IndexKey.DELIVERED_BY):
            continue
        subscriptions = entry.get(IndexKey.SUBSCRIPTIONS)
        if not isinstance(subscriptions, list) or not subscriptions:
            continue
        procedure_id = entry.get(IndexKey.ID)
        if not isinstance(procedure_id, str) or not procedure_id:
            continue
        entries.append(_subscription_entry(procedure_id, entry, subscriptions))
    return SubscriptionPublication(identity=identity, digest=digest, entries=tuple(entries))
