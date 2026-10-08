"""Publishes the platform's declared procedure event subscriptions, their reach, and the index identity."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

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
_TIER_KIND_MISMATCH_ERROR = (
    "Procedure {procedure_id!r} is published in a {tier} tier but answers {answered} events — "
    "refusing rather than widening reach."
)


class IndexKey(StrEnum):
    """The keys of the published merged index this reader consumes."""

    SNIPPETS = "snippets"
    ID = "id"
    TYPE = "type"
    SCOPE = "scope"
    SOURCE_PROJECT = "source_project"
    DELIVERED_BY = "delivered_by"
    SUBSCRIPTIONS = "subscriptions"
    SUBSCRIPTION_HOME = "subscription_home"


class SubscriptionHomeKind(StrEnum):
    """The one kind of home a subscribed procedure answers; ``platform`` answers events of no home."""

    COMPANY = "company"
    PERSON = "person"
    PROJECT = "project"
    PLATFORM = "platform"


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
    """One live procedure's declared patterns, the home kind it answers, and the reach of its tier.

    ``home_slug`` is the one home the publishing tier limits the procedure to,
    or ``None`` for a global procedure, which answers every home of its kind.
    """

    procedure_id: str
    patterns: tuple[TypePattern, ...]
    home_kind: SubscriptionHomeKind
    home_slug: str | None

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


def published_index_identity() -> IndexFileIdentity:
    """The identity of the deployed merged index file as it is now."""
    stat = (GLOBAL_DOCS_DIR / _INDEX_FILE_NAME).stat()
    return IndexFileIdentity(inode=stat.st_ino, modified_ns=stat.st_mtime_ns, size=stat.st_size)


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
    try:
        home_kind = SubscriptionHomeKind(str(entry.get(IndexKey.SUBSCRIPTION_HOME)))
    except ValueError as exc:
        raise ValueError(
            _UNREADABLE_HOME_KIND_ERROR.format(home=entry.get(IndexKey.SUBSCRIPTION_HOME), procedure_id=procedure_id)
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
    )


def published_procedure_subscriptions() -> SubscriptionPublication:
    """Read every live procedure's declared subscriptions from the deployed merged index.

    Reads the one file publication already replaces atomically, so its bytes
    are the version a caller re-derives from on an identity change. Each entry
    carries its parsed type patterns, the home kind it answers, and its tier's
    reach: a ``scope: global`` entry answers every home of its kind, a
    ``scope: company`` or ``scope: person`` entry the one home its
    ``source_project`` token names. An entry whose tier, patterns or home kind
    cannot be read raises. Pending (``delivered_by``) entries are excluded.
    """
    identity = published_index_identity()
    raw = (GLOBAL_DOCS_DIR / _INDEX_FILE_NAME).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    payload = yaml.safe_load(raw.decode(_UTF8)) or {}
    snippets = payload.get(IndexKey.SNIPPETS, []) if isinstance(payload, dict) else []

    entries: list[SubscriptionEntry] = []
    for entry in snippets:
        if not isinstance(entry, dict):
            continue
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
