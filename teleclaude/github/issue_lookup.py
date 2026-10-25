"""Verify a GitHub issue reference in process through the GitHub library."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from githubkit.auth.token import TokenAuthStrategy
from githubkit.auth.unauth import UnauthAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError
from instrukt_ai_logging import get_logger
from pydantic import HttpUrl

from teleclaude.config.loader import github_actor_for_app_id, github_actor_inventory
from teleclaude.core.workflow_store.selection import selected_workflow_store_config
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.types.github_binding import GitHubActorAssignment
from teleclaude.types.github_issue import GitHubIssueReference

logger = get_logger(__name__)

_ISSUE_URL = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/issues/([1-9][0-9]*)/?$")
_ISSUE_NUMBER = re.compile(r"^#?([1-9][0-9]*)$")
_REMOTE_URL = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"
)
_ORIGIN = "origin"
_READ_PERMISSIONS: AppPermissionsType = {"issues": "read"}
_REPOSITORY_SEPARATOR = "/"
_FULL_NAME_TEMPLATE = "{}/{}"
_CREDENTIAL_SKIPPED_EVENT = "github_issue_lookup_credential_skipped"


class IssueLookupFailure(StrEnum):
    """Why an issue could not be identified; never carries the selector or provider text."""

    UNSUPPORTED_SELECTOR = "unsupported_selector"
    NO_REPOSITORY = "no_repository"
    NOT_AN_ISSUE = "not_an_issue"


class IssueLookupUnavailable(RuntimeError):
    """The issue could not be identified now; navigation is optional, so callers keep going."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _RepositoryTarget:
    """The repository an issue lives in, with its stable ID when it is already known."""

    owner: str
    name: str
    number: int
    repository_id: int | None

    @property
    def full_name(self) -> str:
        return _FULL_NAME_TEMPLATE.format(self.owner, self.name)


@dataclass(frozen=True)
class _Scope:
    """Repository facts the credential component scopes an installation token with; no ID scopes by name."""

    repository_id: int | None
    repository: str


async def read_issue_reference(project_path: str, selector: str) -> GitHubIssueReference:
    """Identify the issue a selector names: its verified number and URL from one provider read."""
    target = _resolve_target(project_path, selector)
    try:
        return await _read(project_path, target)
    except (GitHubException, HTTPError, GitHubCredentialRefused, OSError, TimeoutError) as error:
        raise IssueLookupUnavailable(type(error).__name__) from None


def _resolve_target(project_path: str, selector: str) -> _RepositoryTarget:
    declared = selected_workflow_store_config(Path(project_path)).repository
    url = _ISSUE_URL.match(selector)
    if url is not None:
        owner, name, number = url.group(1), url.group(2), int(url.group(3))
        full_name = _FULL_NAME_TEMPLATE.format(owner, name)
        known = declared.id if declared is not None and declared.full_name.casefold() == full_name.casefold() else None
        return _RepositoryTarget(owner, name, number, known)
    bare = _ISSUE_NUMBER.match(selector)
    if bare is None:
        raise IssueLookupUnavailable(IssueLookupFailure.UNSUPPORTED_SELECTOR)
    number = int(bare.group(1))
    if declared is not None:
        owner, _separator, name = declared.full_name.partition(_REPOSITORY_SEPARATOR)
        return _RepositoryTarget(owner, name, number, declared.id)
    origin = _origin_repository(project_path)
    if origin is None:
        raise IssueLookupUnavailable(IssueLookupFailure.NO_REPOSITORY)
    return _RepositoryTarget(origin[0], origin[1], number, None)


def _origin_repository(project_path: str) -> tuple[str, str] | None:
    try:
        repo = Repo(project_path)
        remote_url = next((remote.url for remote in repo.remotes if remote.name == _ORIGIN), None)
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, ValueError):
        return None
    match = _REMOTE_URL.match(remote_url) if remote_url else None
    return (match.group(1), match.group(2)) if match is not None else None


async def _read(project_path: str, target: _RepositoryTarget) -> GitHubIssueReference:
    token = await _installation_token(project_path, target)
    auth: TokenAuthStrategy | UnauthAuthStrategy = (
        TokenAuthStrategy(token) if token is not None else UnauthAuthStrategy()
    )
    async with create_github_client(auth, MemCacheStrategy()) as client:
        response = await client.rest.issues.async_get(target.owner, target.name, target.number)
    issue = response.parsed_data
    if issue.number != target.number or issue.pull_request:
        raise IssueLookupUnavailable(IssueLookupFailure.NOT_AN_ISSUE)
    return GitHubIssueReference(number=issue.number, url=HttpUrl(issue.html_url))


async def _installation_token(project_path: str, target: _RepositoryTarget) -> str | None:
    """Try the project's declared App, then each App of the machine's inventory, for read access to the repository."""
    scope = _Scope(target.repository_id, target.full_name)
    for assignment in _candidates(project_path):
        try:
            credential = await issue_github_installation_credential(assignment, scope, _READ_PERMISSIONS)
        except GitHubCredentialRefused as error:
            logger.debug(_CREDENTIAL_SKIPPED_EVENT, app_id=assignment.app_id, reason=error.reason)
            continue
        return credential.token.get_secret_value()
    return None


def _candidates(project_path: str) -> list[GitHubActorAssignment]:
    declared_app = selected_workflow_store_config(Path(project_path)).app
    candidates: list[GitHubActorAssignment] = []
    if declared_app is not None:
        declared = github_actor_for_app_id(declared_app)
        if declared is not None:
            candidates.append(declared)
    candidates.extend(
        assignment
        for assignment in github_actor_inventory()
        if all(assignment.app_id != chosen.app_id for chosen in candidates)
    )
    return candidates
