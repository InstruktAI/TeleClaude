"""Separate person declarations and platform App references owned by configuration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Self

from pydantic import Field, model_validator

from teleclaude.closed_model import SENSITIVE, ClosedModel
from teleclaude.core.roles import RoleName
from teleclaude.types.github_binding import GitHubActorAssignment

_HANDLE_DESCRIPTION = "Human GitHub account handle; declaration alone establishes no account association."
_HANDLE_TOKEN_PATTERN = r"^[^\s/@]+$"
_ENVIRONMENT_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
_ENVIRONMENT_KEY = re.compile(_ENVIRONMENT_KEY_PATTERN)
_GITHUB_FIELD = "github"
_APPS_FIELD = "apps"
_PRIVATE_KEY_FIELD = "private_key_base64_env"
_BARE_REFERENCE_REQUIRED = "GitHub App private_key_base64_env must be a bare global environment key name"
_AMBIGUOUS_APP = "GitHub App profiles must have unique App and stable Bot identities"
_UNDECLARED_APP = "GitHub role mapping must name a configured App profile"


class GitHubAppProfile(ClosedModel):
    """Declared public actor facts plus an opaque reference, never the key value."""

    assignment: GitHubActorAssignment
    private_key_base64_env: Annotated[str, SENSITIVE] = Field(pattern=_ENVIRONMENT_KEY_PATTERN)


class GlobalGitHubConfig(ClosedModel):
    """Global inventory selected by actual session role, separate from human accounts."""

    apps: list[GitHubAppProfile] = Field(default_factory=list)
    roles: dict[RoleName, Annotated[int, Field(gt=0, strict=True)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unambiguous_apps(self) -> Self:
        """Keep every declared assignment and role reference unambiguous."""
        app_ids = {profile.assignment.app_id for profile in self.apps}
        actor_ids = {profile.assignment.actor.id for profile in self.apps}
        node_ids = {profile.assignment.actor.node_id for profile in self.apps}
        if any(len(values) != len(self.apps) for values in (app_ids, actor_ids, node_ids)):
            raise ValueError(_AMBIGUOUS_APP)
        if any(app_id not in app_ids for app_id in self.roles.values()):
            raise ValueError(_UNDECLARED_APP)
        return self


def require_bare_github_key_references(document: Mapping[str, object]) -> None:
    """Reject key-reference interpolation before generic overlay expansion sees it."""
    github = document.get(_GITHUB_FIELD)
    apps = github.get(_APPS_FIELD) if isinstance(github, Mapping) else None
    if not isinstance(apps, list):
        return
    for profile in apps:
        if not isinstance(profile, Mapping) or _PRIVATE_KEY_FIELD not in profile:
            continue
        reference = profile[_PRIVATE_KEY_FIELD]
        if not isinstance(reference, str) or _ENVIRONMENT_KEY.fullmatch(reference) is None:
            raise ValueError(_BARE_REFERENCE_REQUIRED)


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
