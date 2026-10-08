"""The home a procedure activation concerns: a registered company, person or project, or the platform itself."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.docs_subscriptions import SubscriptionHomeKind
from teleclaude.slug import validate_slug

#: The one slug the platform home carries; the platform is a single home, not a registry entry.
PLATFORM_HOME_SLUG = "teleclaude"
_TOKEN_SEPARATOR = ":"
_PLATFORM_SLUG_ERROR = "the platform home is named {slug!r}, not {given!r}"
_MALFORMED_TOKEN_ERROR = "activation home must be <kind>:<slug> or a bare company slug, got {token!r}"


@dataclass(frozen=True)
class ActivationHome:
    """One activation home: its kind and slug; it can only exist valid."""

    kind: SubscriptionHomeKind
    slug: str

    def __post_init__(self) -> None:
        validate_slug(self.slug)
        if self.kind is SubscriptionHomeKind.PLATFORM and self.slug != PLATFORM_HOME_SLUG:
            raise ValueError(_PLATFORM_SLUG_ERROR.format(slug=PLATFORM_HOME_SLUG, given=self.slug))

    @classmethod
    def platform(cls) -> ActivationHome:
        """The platform home: events concerning no registered home."""
        return cls(SubscriptionHomeKind.PLATFORM, PLATFORM_HOME_SLUG)

    @classmethod
    def from_token(cls, token: str) -> ActivationHome:
        """Parse ``<kind>:<slug>``; a bare slug names a company."""
        kind_text, separator, slug = token.partition(_TOKEN_SEPARATOR)
        if not separator:
            return cls(SubscriptionHomeKind.COMPANY, token)
        try:
            kind = SubscriptionHomeKind(kind_text)
        except ValueError as exc:
            raise ValueError(_MALFORMED_TOKEN_ERROR.format(token=token)) from exc
        return cls(kind, slug)

    def to_token(self) -> str:
        """The token form the activation command carries."""
        return f"{self.kind.value}{_TOKEN_SEPARATOR}{self.slug}"

    @property
    def company(self) -> str | None:
        """The company a session for this home is bound to; only a company home has one."""
        return self.slug if self.kind is SubscriptionHomeKind.COMPANY else None
