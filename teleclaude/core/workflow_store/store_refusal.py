"""Name a project's workflow-store refusal in plain words and the act that resolves it."""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.workflow_store.github import GitHubIdentityRefusal, GitHubIdentityRefused
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_store import GitHubStoreSelectionRefused
from teleclaude.paths import PROJECTS_MANIFEST_PATH, ConfigFileName

_GITHUB_UNREACHABLE = frozenset({GitHubIdentityRefusal.RATE_LIMITED, GitHubIdentityRefusal.PROVIDER_UNAVAILABLE})
_GITHUB_UNREACHABLE_DETAIL = (
    "the GitHub workflow store could not be reached ({reason}). Retry, or check `telec app status`."
)
_GITHUB_CREDENTIAL_DETAIL = (
    "GitHub refused the credential of the platform App that `todos.app` in {declaration} names ({reason}). "
    "Check that App's profile with `telec config global get github.apps`, that the environment variable its "
    "`private_key_base64_env` names holds the App's private key (`telec config env set`), and that the App is "
    "installed on the project's repository."
)
_ISSUE_ARTIFACTS_DETAIL = (
    "GitHub does not serve issue artifacts on the repository that `todos.repository` in {declaration} names "
    "to the platform App that `todos.app` names ({reason}), so this project's workflow store is refused. "
    "Have the repository's organization serve GitHub issue artifacts and grant that App's installation the "
    "repository permissions GitHub requires to read them; the store probes again on its next use and serves "
    "once GitHub answers."
)


def _describe_identity_refusal(reason: GitHubIdentityRefusal, project_root: Path) -> str:
    """Name a GitHub identity refusal and its door."""
    declaration = project_root / ConfigFileName.OVERLAY
    if reason is GitHubIdentityRefusal.UNREGISTERED_PROJECT:
        return (
            f"{project_root} is not a registered project in {PROJECTS_MANIFEST_PATH}. "
            "Register it by running `telec config project adopt` from that folder."
        )
    if reason is GitHubIdentityRefusal.REPOSITORY_UNDECLARED:
        return (
            f"the project selects the GitHub workflow store but declares no repository ({reason}). "
            f"Declare `todos.repository` in {declaration}."
        )
    if reason is GitHubIdentityRefusal.CREDENTIAL_REFUSED:
        return _GITHUB_CREDENTIAL_DETAIL.format(declaration=declaration, reason=reason)
    if reason in _GITHUB_UNREACHABLE:
        return _GITHUB_UNREACHABLE_DETAIL.format(reason=reason)
    return f"the GitHub workflow store refused this project ({reason})."


def _describe_io_refusal(reason: GitHubIOFailure, project_root: Path) -> str:
    """Name a GitHub I/O refusal: a refused credential and unserved issue artifacts have their own doors."""
    declaration = project_root / ConfigFileName.OVERLAY
    if reason is GitHubIOFailure.CREDENTIAL_REFUSED:
        return _GITHUB_CREDENTIAL_DETAIL.format(declaration=declaration, reason=reason)
    if reason is GitHubIOFailure.ISSUE_ARTIFACTS_UNAVAILABLE:
        return _ISSUE_ARTIFACTS_DETAIL.format(declaration=declaration, reason=reason)
    return _GITHUB_UNREACHABLE_DETAIL.format(reason=reason)


type StoreRefusal = GitHubIdentityRefused | GitHubStoreSelectionRefused | GitHubIORefused
STORE_REFUSALS = (GitHubIdentityRefused, GitHubStoreSelectionRefused, GitHubIORefused)


def describe_store_refusal(error: StoreRefusal, project_root: Path) -> str:
    """Name a workflow-store refusal for the project and its door."""
    if isinstance(error, GitHubIdentityRefused):
        return _describe_identity_refusal(error.reason, project_root)
    if isinstance(error, GitHubStoreSelectionRefused):
        return f"{error}. Fix `todos.app` in {project_root / ConfigFileName.OVERLAY}."
    return _describe_io_refusal(error.reason, project_root)
