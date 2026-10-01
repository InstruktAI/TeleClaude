"""Lightweight owner for snippet publication scopes and home identity prefixes."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from teleclaude.paths import COMPANIES_ROOT, PEOPLE_DIR

_PROJECTS_IDENTITY_PREFIX: Final = "projects"


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


def home_identity_prefix(scope: SnippetScope) -> str:
    """Return the plural identity prefix for a home kind."""
    return HOME_IDENTITY_PREFIXES[scope]


def home_scope_for_prefix(prefix: str) -> SnippetScope | None:
    """Return the home kind an identity's first segment names, or ``None``."""
    return _HOME_SCOPE_BY_PREFIX.get(prefix)
