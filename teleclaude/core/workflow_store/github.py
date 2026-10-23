"""GitHub workflow-store adapter and native target projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Final
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError
from instrukt_ai_logging import get_logger

from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.core.workflow_store.selection import selected_workflow_store_config
from teleclaude.core.workflow_store.types import ItemIdentity, StoreAddress, WorkItemId
from teleclaude.github.accounts import GitHubRateLimitFacts
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import (
    GitHubCredentialFailure,
    GitHubCredentialRefused,
    issue_github_installation_credential,
)
from teleclaude.project_manifest import load_registered_roots
from teleclaude.types.github_binding import GitHubActorAssignment, GitHubWorkTarget

_INVALID_GITHUB_WORK_ITEM_ID = "GitHub work item ID must be a canonical positive ASCII decimal issue number"
_ZERO_PREFIX = "0"
_REPOSITORY_SEPARATOR = "/"
_EMPTY = ""
_ITEM_READ_PERMISSIONS: Final[AppPermissionsType] = {"issues": "read"}
_PULL_REQUEST_FIELD = "pull_request"
_ISSUE_UNAVAILABLE_STATUSES = frozenset({301, 404, 410})
_INVALID_WORK_ITEM_ID_REASON = "invalid_work_item_id"
_READ_REFUSED_EVENT = "github_item_identity_refused"
_READ_COMPLETED_EVENT = "github_item_identity_read"
logger = get_logger(__name__)


@dataclass(frozen=True)
class GitHubRepositoryIdentity:
    """Repository identity selected for a project's GitHub workflow store."""

    project_path: Path
    repository_id: int
    repository: str


class GitHubIdentityRefusal(StrEnum):
    """Bounded refusal reasons for GitHub workflow identity operations."""

    UNREGISTERED_PROJECT = "unregistered_project"
    STORE_NOT_GITHUB = "store_not_github"
    REPOSITORY_UNDECLARED = "repository_undeclared"
    CREDENTIAL_REFUSED = "credential_refused"
    ITEM_UNAVAILABLE = "item_unavailable"
    NOT_AN_ISSUE = "not_an_issue"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_WORK_ITEM_ID = _INVALID_WORK_ITEM_ID_REASON


class GitHubIdentityRefused(RuntimeError):
    """A GitHub workflow identity could not be established safely."""

    def __init__(
        self,
        reason: GitHubIdentityRefusal,
        *,
        credential_failure: GitHubCredentialFailure | None = None,
        rate_limit: GitHubRateLimitFacts | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.credential_failure = credential_failure
        self.rate_limit = rate_limit


class InvalidGitHubWorkItemId(ValueError):
    """A workflow item ID does not encode a canonical GitHub issue number."""


def resolve_github_repository_identity(project_root_or_cwd: str | Path) -> GitHubRepositoryIdentity:
    """Resolve declared repository identity for a present, registered GitHub project."""
    try:
        project_root = resolve_project_state_root(project_root_or_cwd)
    except FileNotFoundError:
        raise GitHubIdentityRefused(GitHubIdentityRefusal.UNREGISTERED_PROJECT) from None

    registered = any(entry.is_present and entry.path.resolve() == project_root for entry in load_registered_roots())
    if not registered:
        raise GitHubIdentityRefused(GitHubIdentityRefusal.UNREGISTERED_PROJECT)

    config = selected_workflow_store_config(project_root)
    if config.store is not TodoStoreBackend.GITHUB:
        raise GitHubIdentityRefused(GitHubIdentityRefusal.STORE_NOT_GITHUB)
    if config.repository is None:
        raise GitHubIdentityRefused(GitHubIdentityRefusal.REPOSITORY_UNDECLARED)
    return GitHubRepositoryIdentity(
        project_path=project_root,
        repository_id=config.repository.id,
        repository=config.repository.full_name,
    )


def _github_work_item_target(
    repository_identity: GitHubRepositoryIdentity, work_item_id: WorkItemId
) -> GitHubWorkTarget:
    """Parse a canonical issue key and construct its identity-only target."""
    work_item = str(work_item_id)
    if not work_item.isascii() or not work_item.isdecimal() or work_item.startswith(_ZERO_PREFIX):
        raise InvalidGitHubWorkItemId(_INVALID_GITHUB_WORK_ITEM_ID)

    try:
        issue_number = int(work_item)
    except ValueError as exc:
        raise InvalidGitHubWorkItemId(_INVALID_GITHUB_WORK_ITEM_ID) from exc

    return GitHubWorkTarget(
        repository_id=repository_identity.repository_id,
        repository=repository_identity.repository,
        issue_number=issue_number,
        work_item=work_item,
        project_path=repository_identity.project_path,
    )


def project_github_work_target(
    repository_identity: GitHubRepositoryIdentity,
    work_item_id: WorkItemId,
    store_address: StoreAddress,
) -> GitHubWorkTarget:
    """Project a selected repository and item identity to its native GitHub target.

    The opaque store address is intentionally projected away. Its correspondence
    with the work item ID is guaranteed by the selected adapter's identity
    invariant; this pure projection performs no lookup or provider call.
    """
    return _github_work_item_target(repository_identity, work_item_id)


async def read_github_item_identity(
    repository_identity: GitHubRepositoryIdentity,
    work_item_id: WorkItemId,
    assignment: GitHubActorAssignment,
) -> ItemIdentity:
    """Read an issue's node ID and its canonical key from one provider response."""
    started_at = perf_counter()
    cache = MemCacheStrategy()
    try:
        target = _github_work_item_target(repository_identity, work_item_id)
        credential = await issue_github_installation_credential(assignment, target, _ITEM_READ_PERMISSIONS)
        owner, _, repository = repository_identity.repository.partition(_REPOSITORY_SEPARATOR)
        async with create_github_client(TokenAuthStrategy(credential.token.get_secret_value()), cache) as client:
            response = await client.rest.issues.async_get(
                quote(owner, safe=_EMPTY), quote(repository, safe=_EMPTY), target.issue_number
            )
        if response.status_code in _ISSUE_UNAVAILABLE_STATUSES:
            raise GitHubIdentityRefused(GitHubIdentityRefusal.ITEM_UNAVAILABLE)
        if response.status_code != 200:
            raise GitHubIdentityRefused(GitHubIdentityRefusal.PROVIDER_UNAVAILABLE)
        issue = response.parsed_data
        if _PULL_REQUEST_FIELD in issue.model_fields_set:
            raise GitHubIdentityRefused(GitHubIdentityRefusal.NOT_AN_ISSUE)
        if issue.number != target.issue_number or not issue.node_id.strip():
            raise GitHubIdentityRefused(GitHubIdentityRefusal.PROVIDER_UNAVAILABLE)
        logger.debug(
            _READ_COMPLETED_EVENT,
            event=_READ_COMPLETED_EVENT,
            repository_id=repository_identity.repository_id,
            issue_number=target.issue_number,
            duration_ms=int((perf_counter() - started_at) * 1000),
        )
        return ItemIdentity(work_item_id=work_item_id, store_address=StoreAddress(issue.node_id))
    except GitHubCredentialRefused as error:
        reason = GitHubIdentityRefusal.CREDENTIAL_REFUSED
        logger.warning(
            _READ_REFUSED_EVENT,
            event=_READ_REFUSED_EVENT,
            reason=reason,
            repository_id=repository_identity.repository_id,
        )
        raise GitHubIdentityRefused(
            reason,
            credential_failure=error.reason,
            rate_limit=error.rate_limit,
        ) from None
    except RateLimitExceeded as error:
        rate_limit = GitHubRateLimitFacts.from_sdk(error)
        logger.warning(
            _READ_REFUSED_EVENT,
            event=_READ_REFUSED_EVENT,
            reason=GitHubIdentityRefusal.RATE_LIMITED,
            repository_id=repository_identity.repository_id,
        )
        raise GitHubIdentityRefused(GitHubIdentityRefusal.RATE_LIMITED, rate_limit=rate_limit) from None
    except GitHubIdentityRefused as error:
        logger.warning(
            _READ_REFUSED_EVENT,
            event=_READ_REFUSED_EVENT,
            reason=error.reason,
            repository_id=repository_identity.repository_id,
        )
        raise
    except InvalidGitHubWorkItemId:
        logger.warning(
            _READ_REFUSED_EVENT,
            event=_READ_REFUSED_EVENT,
            reason=GitHubIdentityRefusal.INVALID_WORK_ITEM_ID,
            repository_id=repository_identity.repository_id,
        )
        raise
    except GitHubException as error:
        status_code = error.response.status_code if isinstance(error, RequestFailed) else None
        reason = (
            GitHubIdentityRefusal.ITEM_UNAVAILABLE
            if status_code in _ISSUE_UNAVAILABLE_STATUSES
            else GitHubIdentityRefusal.PROVIDER_UNAVAILABLE
        )
        logger.warning(
            _READ_REFUSED_EVENT,
            event=_READ_REFUSED_EVENT,
            reason=reason,
            repository_id=repository_identity.repository_id,
        )
        raise GitHubIdentityRefused(reason) from None
    except (HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        logger.warning(
            _READ_REFUSED_EVENT,
            event=_READ_REFUSED_EVENT,
            reason=GitHubIdentityRefusal.PROVIDER_UNAVAILABLE,
            repository_id=repository_identity.repository_id,
        )
        raise GitHubIdentityRefused(GitHubIdentityRefusal.PROVIDER_UNAVAILABLE) from None
    finally:
        await cache.acleanup()
