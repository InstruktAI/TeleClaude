"""Lightweight owner for snippet publication scopes and home identity prefixes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from teleclaude.paths import COMPANIES_ROOT, PEOPLE_DIR

_PROJECTS_IDENTITY_PREFIX: Final = "projects"
_LOCAL_IDENTITY_PREFIX: Final = "local"
_IDENTITY_SEPARATOR: Final = "/"


class SnippetScope(StrEnum):
    """Closed scope values materialized in the snippet index."""

    GLOBAL = "global"
    PROJECT = "project"
    PERSON = "person"
    COMPANY = "company"


#: The only owner of the plural identity prefixes that open a home's snippet
#: identity: ``projects/<slug>/…``, ``people/<slug>/…``, ``companies/<slug>/…``.
#: Scope values stay singular; only identities carry the plural prefix.
HOME_IDENTITY_PREFIXES: Final[MappingProxyType[SnippetScope, str]] = MappingProxyType(
    {
        SnippetScope.PROJECT: _PROJECTS_IDENTITY_PREFIX,
        SnippetScope.PERSON: PEOPLE_DIR.name,
        SnippetScope.COMPANY: COMPANIES_ROOT.name,
    }
)

_HOME_SCOPE_BY_PREFIX: Final[MappingProxyType[str, SnippetScope]] = MappingProxyType(
    {prefix: scope for scope, prefix in HOME_IDENTITY_PREFIXES.items()}
)

#: Home kinds whose snippets carry an owner segment in their identity.
HOME_SCOPES: Final[frozenset[SnippetScope]] = frozenset(HOME_IDENTITY_PREFIXES)


class HomeSnippetHalf(StrEnum):
    """The publication half named by a home snippet identity."""

    PUBLISHED = "published"
    LOCAL = "local"


@dataclass(frozen=True)
class HomeSnippetIdentity:
    """Parsed home identity, including its half and taxonomy tail."""

    scope: SnippetScope
    owner: str
    half: HomeSnippetHalf
    taxonomy: str
    rest: str


RESERVED_HOME_IDENTITY_PREFIXES: Final[frozenset[str]] = frozenset(
    {*HOME_IDENTITY_PREFIXES.values(), _LOCAL_IDENTITY_PREFIX}
)


def home_identity_prefix(scope: SnippetScope, *, local: bool = False) -> str:
    """Return the identity prefix for a home kind and publication half."""
    prefix = HOME_IDENTITY_PREFIXES[scope]
    return _IDENTITY_SEPARATOR.join((_LOCAL_IDENTITY_PREFIX, prefix)) if local else prefix


def home_scope_for_prefix(prefix: str) -> SnippetScope | None:
    """Return the home kind an identity's first segment names, or ``None``."""
    return _HOME_SCOPE_BY_PREFIX.get(prefix)


def parse_home_snippet_id(value: str) -> HomeSnippetIdentity | None:
    """Parse a qualified person, company, or local project snippet identity."""
    parts = value.strip().strip(_IDENTITY_SEPARATOR).split(_IDENTITY_SEPARATOR)
    if parts[0] == _LOCAL_IDENTITY_PREFIX:
        if len(parts) < 5:
            return None
        scope = home_scope_for_prefix(parts[1])
        owner_index = 2
        half = HomeSnippetHalf.LOCAL
    else:
        scope = home_scope_for_prefix(parts[0])
        if scope is SnippetScope.PROJECT or scope is None or len(parts) < 4:
            return None
        owner_index = 1
        half = HomeSnippetHalf.PUBLISHED
    if scope is None:
        return None
    owner = parts[owner_index]
    taxonomy = parts[owner_index + 1]
    rest = _IDENTITY_SEPARATOR.join(parts[owner_index + 2 :])
    if not owner or not taxonomy or not rest:
        return None
    return HomeSnippetIdentity(scope=scope, owner=owner, half=half, taxonomy=taxonomy, rest=rest)
