"""Person-owned GitHub declarations, separate from provider credentials."""

from __future__ import annotations

from pydantic import Field

from teleclaude.closed_model import ClosedModel

_HANDLE_DESCRIPTION = "Human GitHub account handle; declaration alone establishes no account association."
_HANDLE_TOKEN_PATTERN = r"^[^\s/@]+$"


class PersonGitHubIdentity(ClosedModel):
    """The person's declared human account, with no credential fallback."""

    handle: str | None = Field(
        default=None,
        min_length=1,
        pattern=_HANDLE_TOKEN_PATTERN,
        description=_HANDLE_DESCRIPTION,
    )


class PersonGitHubConfig(ClosedModel):
    """GitHub settings owned exclusively by a person's overlay."""

    identity: PersonGitHubIdentity = Field(default_factory=PersonGitHubIdentity)
