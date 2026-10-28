"""Issue one verified repository-scoped App credential through the standard SDK."""

from __future__ import annotations

from asyncio import timeout, to_thread
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, TypedDict
from urllib.parse import quote

from githubkit.auth.app import AppAuthStrategy
from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded
from githubkit_schemas.v2026_03_10.models import InstallationToken
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from instrukt_ai_logging import get_logger
from jwt.exceptions import PyJWTError
from pydantic import SecretStr

from teleclaude.config.loader import GitHubAppKeyFailure, GitHubAppKeyRefused, resolve_github_app_private_key
from teleclaude.github.accounts import GitHubAccountDirectory, GitHubAccountLookupRefused, GitHubRateLimitFacts
from teleclaude.github.client import RequestGate, create_github_client
from teleclaude.types.github_account import github_app_bot_login
from teleclaude.types.github_binding import GitHubActorAssignment

logger = get_logger(__name__)
_REFUSAL_LOG = "github_credential_refused reason=%s app_id=%s repository_id=%s"
_ISSUED_LOG = "github_credential_issued app_id=%s installation_id=%s repository_id=%s"
_OPERATION_TIMEOUT_SECONDS = 60.0
_MINIMUM_LIFETIME = timedelta(minutes=1)
_METADATA_PERMISSION = "metadata"
_PERMISSIONS_FIELD = "permissions"
_POST = "POST"
_ACCESS_TOKENS_PATH = "/app/installations/{installation_id}/access_tokens"
_REPOSITORY_SEPARATOR = "/"
_SELECTED_REPOSITORIES = "selected"
_EMPTY = ""


class _GitHubRepositoryScope(Protocol):
    """Repository identity needed to scope an installation credential.

    A scope without a numeric ID names the repository only: its token is requested by repository
    name and accepted only when GitHub returns exactly that one repository.
    """

    @property
    def repository_id(self) -> int | None: ...

    @property
    def repository(self) -> str: ...


class GitHubCredentialFailure(StrEnum):
    """Bounded failures that never carry credential or provider response text."""

    KEY_UNAVAILABLE = "key_unavailable"
    APP_MISMATCH = "app_mismatch"
    INSTALLATION_UNAVAILABLE = "installation_unavailable"
    SCOPE_UNVERIFIED = "scope_unverified"
    EXPIRY_UNVERIFIED = "expiry_unverified"
    ACTOR_MISMATCH = "actor_mismatch"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"


class GitHubCredentialRefused(RuntimeError):
    """No credential may be forwarded to a provider child."""

    def __init__(
        self,
        reason: GitHubCredentialFailure,
        *,
        rate_limit: GitHubRateLimitFacts | None = None,
        key_failure: GitHubAppKeyFailure | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rate_limit = rate_limit
        self.key_failure = key_failure


@dataclass(frozen=True)
class GitHubInstallationCredential:
    """Memory-only result for an authorized child; never a persisted session binding."""

    token: SecretStr
    expires_at: datetime
    installation_id: int
    assignment: GitHubActorAssignment
    target: _GitHubRepositoryScope


class _AccessLevel(StrEnum):
    """The access levels a GitHub App permission carries."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class _AccessTokenRequest(TypedDict, total=False):
    """The installation access token request body."""

    permissions: AppPermissionsType
    repository_ids: list[int]
    repositories: list[str]


def _permission_values(permissions: object) -> dict[str, str]:
    """Each permission name with its access level, as sent or received.

    The raw mapping is read rather than the typed model, which drops a permission newer than its schema; every
    level must still be a plain access level.
    """
    if not isinstance(permissions, Mapping):
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    values: dict[str, str] = {}
    for name, value in permissions.items():
        if not isinstance(name, str) or value not in _AccessLevel:
            raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
        values[name] = value
    return values


def _verify_issued_scope(
    issued: InstallationToken,
    issued_permissions: object,
    target: _GitHubRepositoryScope,
    requested_permissions: dict[str, str],
) -> datetime:
    if (
        not issued.token.strip()
        or issued.repository_selection != _SELECTED_REPOSITORIES
        or not isinstance(issued.repositories, list)
        or len(issued.repositories) != 1
    ):
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    repository = issued.repositories[0]
    if (
        target.repository_id is not None and repository.id != target.repository_id
    ) or repository.full_name.casefold() != target.repository.casefold():
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    granted_permissions = _permission_values(issued_permissions)
    permitted = {**requested_permissions, _METADATA_PERMISSION: _AccessLevel.READ}
    if any(granted_permissions.get(name) != level for name, level in requested_permissions.items()):
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    if any(permitted.get(name) != level for name, level in granted_permissions.items()):
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    try:
        expiry = datetime.fromisoformat(issued.expires_at)
    except ValueError:
        raise GitHubCredentialRefused(GitHubCredentialFailure.EXPIRY_UNVERIFIED) from None
    if expiry.utcoffset() is None or expiry <= datetime.now(UTC) + _MINIMUM_LIFETIME:
        raise GitHubCredentialRefused(GitHubCredentialFailure.EXPIRY_UNVERIFIED)
    return expiry


async def issue_github_installation_credential(
    assignment: GitHubActorAssignment,
    target: _GitHubRepositoryScope,
    permissions: AppPermissionsType,
    *,
    request_gate: RequestGate | None = None,
) -> GitHubInstallationCredential:
    """Consume owner-selected facts and the config-owned key before verified token export.

    A caller that schedules provider traffic passes `request_gate`; each request of the issuance runs inside it.

    The trusted composition calls this only after invocation/operation admission.
    No argument is an actor selector at a native command boundary. This component
    asks only config for the recorded App's SecretStr, never a caller-selected reference.
    """
    cache = MemCacheStrategy()
    try:
        requested = deepcopy(permissions)
        requested_permissions = _permission_values(requested)
        if not requested_permissions:
            raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
        private_key = await to_thread(resolve_github_app_private_key, assignment)
        async with (
            timeout(_OPERATION_TIMEOUT_SECONDS),
            create_github_client(
                AppAuthStrategy(app_id=assignment.app_id, private_key=private_key.get_secret_value()),
                cache,
                request_gate=request_gate,
            ) as app_client,
        ):
            app_response = await app_client.rest.apps.async_get_authenticated()
            app = app_response.parsed_data
            if app_response.status_code != 200 or app is None or app.id != assignment.app_id:
                raise GitHubCredentialRefused(GitHubCredentialFailure.APP_MISMATCH)
            if not isinstance(app.slug, str) or not app.slug:
                raise GitHubCredentialRefused(GitHubCredentialFailure.APP_MISMATCH)
            owner, repository = target.repository.split(_REPOSITORY_SEPARATOR)
            installation_response = await app_client.rest.apps.async_get_repo_installation(
                quote(owner, safe=_EMPTY), quote(repository, safe=_EMPTY)
            )
            installation = installation_response.parsed_data
            if (
                installation_response.status_code != 200
                or installation.id <= 0
                or installation.app_id != assignment.app_id
                or installation.suspended_at is not None
                or installation.suspended_by is not None
            ):
                raise GitHubCredentialRefused(GitHubCredentialFailure.INSTALLATION_UNAVAILABLE)
            # Sent as plain JSON: the typed request drops a permission newer than its schema, and GitHub would
            # then issue the installation's full scope instead of the one requested.
            body = _AccessTokenRequest(permissions=requested)
            if target.repository_id is not None:
                body["repository_ids"] = [target.repository_id]
            else:
                body["repositories"] = [repository]
            response = await app_client.arequest(
                _POST,
                _ACCESS_TOKENS_PATH.format(installation_id=installation.id),
                json=body,
                response_model=InstallationToken,
            )
            if response.status_code != 201:
                raise GitHubCredentialRefused(GitHubCredentialFailure.PROVIDER_UNAVAILABLE)
            issued = response.parsed_data
            issued_permissions = response.json().get(_PERMISSIONS_FIELD)
            expiry = _verify_issued_scope(issued, issued_permissions, target, requested_permissions)
            # Account metadata needs an installation token; /user is not App identity.
            async with create_github_client(
                TokenAuthStrategy(issued.token), cache, request_gate=request_gate
            ) as token_client:
                account = await GitHubAccountDirectory(token_client).read(github_app_bot_login(app.slug))
                if not account.same_account(assignment.actor):
                    raise GitHubCredentialRefused(GitHubCredentialFailure.ACTOR_MISMATCH)
            # Metadata reads consume time too; do not export a credential about to expire.
            if expiry <= datetime.now(UTC) + _MINIMUM_LIFETIME:
                raise GitHubCredentialRefused(GitHubCredentialFailure.EXPIRY_UNVERIFIED)
            logger.info(_ISSUED_LOG, assignment.app_id, installation.id, target.repository_id)
            return GitHubInstallationCredential(
                token=SecretStr(issued.token),
                expires_at=expiry,
                installation_id=installation.id,
                assignment=assignment,
                target=target,
            )
    except GitHubAppKeyRefused as error:
        logger.warning(_REFUSAL_LOG, GitHubCredentialFailure.KEY_UNAVAILABLE, assignment.app_id, target.repository_id)
        raise GitHubCredentialRefused(GitHubCredentialFailure.KEY_UNAVAILABLE, key_failure=error.reason) from None
    except GitHubCredentialRefused as error:
        logger.warning(_REFUSAL_LOG, error.reason, assignment.app_id, target.repository_id)
        raise
    except (GitHubException, GitHubAccountLookupRefused, PyJWTError, TimeoutError, ValueError) as error:
        # SDK/crypto exceptions can contain request headers or key/parser details.
        rate_limit = None
        if isinstance(error, RateLimitExceeded):
            rate_limit = GitHubRateLimitFacts.from_sdk(error)
        elif isinstance(error, GitHubAccountLookupRefused):
            rate_limit = error.rate_limit
        reason = GitHubCredentialFailure.RATE_LIMITED if rate_limit else GitHubCredentialFailure.PROVIDER_UNAVAILABLE
        logger.warning(_REFUSAL_LOG, reason, assignment.app_id, target.repository_id)
        raise GitHubCredentialRefused(reason, rate_limit=rate_limit) from None
    finally:
        await cache.acleanup()
