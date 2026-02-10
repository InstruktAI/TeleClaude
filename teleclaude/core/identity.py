"""Identity management and resolution for multi-person deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from teleclaude.config.loader import load_global_config

if TYPE_CHECKING:
    from teleclaude.config.schema import PersonEntry


@dataclass(frozen=True)
class IdentityContext:
    """Normalized identity result with resolution source."""

    email: str
    role: str
    username: Optional[str] = None
    resolution_source: str = "unknown"  # "email", "username", "header", "token"


class IdentityResolver:
    """Multi-signal identity resolver (email primary, username secondary)."""

    def __init__(self, people: list[PersonEntry]) -> None:
        """Initialize resolver with configured people.

        Args:
            people: List of PersonEntry from global config.
        """
        self._by_email: dict[str, PersonEntry] = {p.email.lower(): p for p in people}
        self._by_username: dict[str, PersonEntry] = {p.username.lower(): p for p in people if p.username}

    def resolve_by_email(self, email: str) -> Optional[IdentityContext]:
        """Resolve identity by email (primary signal)."""
        entry = self._by_email.get(email.lower())
        if not entry:
            return None

        return IdentityContext(
            email=entry.email,
            role=entry.role,
            username=entry.username,
            resolution_source="email",
        )

    def resolve_by_username(self, username: str) -> Optional[IdentityContext]:
        """Resolve identity by username (secondary signal)."""
        entry = self._by_username.get(username.lower())
        if not entry:
            return None

        return IdentityContext(
            email=entry.email,
            role=entry.role,
            username=entry.username,
            resolution_source="username",
        )


# Singleton resolver instance
_resolver: Optional[IdentityResolver] = None


def get_identity_resolver() -> IdentityResolver:
    """Get the configured identity resolver (bootstrap on first call)."""
    global _resolver
    if _resolver is None:
        global_config = load_global_config()
        _resolver = IdentityResolver(global_config.people)
    return _resolver
