"""GitHub human-account binding composed with the existing person-context owner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.loader import load_person_config
from teleclaude.core.identity import (
    IdentityResolver,
    PersonContextBindingRefusal,
    PersonContextBindingRegistryError,
    RefusedPersonContextBinding,
)
from teleclaude.github.accounts import (
    GitHubAccount,
    GitHubAccountDirectory,
    GitHubAccountKind,
    GitHubAccountLookupRefused,
)
from teleclaude.paths import ConfigFileName


class GitHubPersonRefusal(StrEnum):
    """Identity-owned reasons a GitHub account establishes no person binding."""

    DECLARATION_UNREADABLE = "declaration_unreadable"
    PERSON_CONTEXT_UNRESOLVED = "person_context_unresolved"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    ABSENT = "absent"
    ACCOUNT_UNAVAILABLE = "account_unavailable"
    NON_HUMAN_ACCOUNT = "non_human_account"
    ACCOUNT_MISMATCH = "account_mismatch"


@dataclass(frozen=True)
class AcceptedGitHubPersonBinding:
    """A validated person/account identity fact, carrying no workflow grant."""

    person: PersonEntry
    account: GitHubAccount


@dataclass(frozen=True)
class RefusedGitHubPersonBinding:
    """A failed person/account association with its original context refusal."""

    reason: GitHubPersonRefusal
    context_refusal: PersonContextBindingRefusal | None = None


GitHubPersonBinding = AcceptedGitHubPersonBinding | RefusedGitHubPersonBinding


async def resolve_github_person_binding(
    context_root: Path,
    authenticated_account: GitHubAccount,
    *,
    identity: IdentityResolver,
    accounts: GitHubAccountDirectory,
) -> GitHubPersonBinding:
    """Validate the declared home before resolving its account through the provider."""
    try:
        declared = load_person_config(context_root / ConfigFileName.OVERLAY)
    except (OSError, ValueError, yaml.YAMLError):
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.DECLARATION_UNREADABLE)
    try:
        context = identity.resolve_person_context_binding(declared.slug, context_root)
    except PersonContextBindingRegistryError:
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.REGISTRY_UNAVAILABLE)
    if isinstance(context, RefusedPersonContextBinding):
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.PERSON_CONTEXT_UNRESOLVED, context.refusal)
    handle = declared.github.identity.handle
    if handle is None:
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.ABSENT)
    if authenticated_account.type is not GitHubAccountKind.USER:
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.NON_HUMAN_ACCOUNT)
    try:
        declared_account = await accounts.read(handle)
    except GitHubAccountLookupRefused:
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.ACCOUNT_UNAVAILABLE)
    if declared_account.type is not GitHubAccountKind.USER:
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.NON_HUMAN_ACCOUNT)
    if not declared_account.same_account(authenticated_account):
        return RefusedGitHubPersonBinding(GitHubPersonRefusal.ACCOUNT_MISMATCH)
    return AcceptedGitHubPersonBinding(context.person, declared_account)
