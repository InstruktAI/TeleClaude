"""Issue one verified repository-scoped App credential through the standard SDK."""

from __future__ import annotations

from asyncio import timeout
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import quote

from githubkit.auth.app import AppAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException
from githubkit.github import GitHub
from githubkit_schemas.v2026_03_10.models import AppPermissions, InstallationToken
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from instrukt_ai_logging import get_logger
from jwt.exceptions import PyJWTError
from pydantic import SecretStr

from teleclaude.github.accounts import GitHubAccountDirectory, GitHubAccountLookupRefused
from teleclaude.types.github_binding import GitHubActorAssignment, GitHubWorkTarget

logger = get_logger(__name__)
_REFUSAL_LOG = "github_credential_refused reason=%s app_id=%s repository_id=%s"
_ISSUED_LOG = "github_credential_issued app_id=%s installation_id=%s repository_id=%s"
_TIMEOUT_SECONDS = 10.0
_OPERATION_TIMEOUT_SECONDS = 60.0
_MINIMUM_LIFETIME = timedelta(minutes=1)
_BOT_LOGIN = "{slug}[bot]"
_METADATA_PERMISSION = "metadata"
_READ_PERMISSION = "read"
_REPOSITORY_SEPARATOR = "/"
_SELECTED_REPOSITORIES = "selected"
_EMPTY = ""


class GitHubCredentialFailure(StrEnum):
    """Bounded failures that never carry credential or provider response text."""

    KEY_UNAVAILABLE = "key_unavailable"
    APP_MISMATCH = "app_mismatch"
    INSTALLATION_UNAVAILABLE = "installation_unavailable"
    SCOPE_UNVERIFIED = "scope_unverified"
    EXPIRY_UNVERIFIED = "expiry_unverified"
    ACTOR_MISMATCH = "actor_mismatch"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class GitHubCredentialRefused(RuntimeError):
    """No credential may be forwarded to a provider child."""

    def __init__(self, reason: GitHubCredentialFailure) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GitHubInstallationCredential:
    """Memory-only result for an authorized child; never a persisted session binding."""

    token: SecretStr
    expires_at: datetime
    installation_id: int
    assignment: GitHubActorAssignment
    target: GitHubWorkTarget


def _permission_values(permissions: AppPermissions) -> dict[str, str]:
    if permissions.model_extra:
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    values: dict[str, str] = {}
    for name, value in permissions.model_dump(exclude_unset=True).items():
        if not isinstance(value, str):
            raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
        values[name] = value
    return values


def _verify_issued_scope(
    issued: InstallationToken,
    target: GitHubWorkTarget,
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
    if repository.id != target.repository_id or repository.full_name.casefold() != target.repository.casefold():
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    if not isinstance(issued.permissions, AppPermissions):
        raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
    granted_permissions = _permission_values(issued.permissions)
    permitted = {**requested_permissions, _METADATA_PERMISSION: _READ_PERMISSION}
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
    target: GitHubWorkTarget,
    permissions: AppPermissionsType,
    *,
    private_key: SecretStr,
) -> GitHubInstallationCredential:
    """Consume owner-selected facts/key and verify SDK issuance before child token export.

    The trusted composition calls this only after invocation/operation admission.
    No argument is an actor selector at a native command boundary. This component
    does not resolve protected key references or replace their configuration owner.
    """
    cache = MemCacheStrategy()
    try:
        if not private_key.get_secret_value():
            raise GitHubCredentialRefused(GitHubCredentialFailure.KEY_UNAVAILABLE)
        requested = deepcopy(permissions)
        requested_permissions = _permission_values(AppPermissions.model_validate(requested))
        if not requested_permissions:
            raise GitHubCredentialRefused(GitHubCredentialFailure.SCOPE_UNVERIFIED)
        async with (
            timeout(_OPERATION_TIMEOUT_SECONDS),
            GitHub(
                AppAuthStrategy(app_id=assignment.app_id, private_key=private_key.get_secret_value()),
                cache_strategy=cache,
                auto_retry=False,
                http_cache=False,
                follow_redirects=False,
                trust_env=False,
                timeout=_TIMEOUT_SECONDS,
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
            response = await app_client.rest.apps.async_create_installation_access_token(
                installation.id,
                repository_ids=[target.repository_id],
                permissions=requested,
            )
            if response.status_code != 201:
                raise GitHubCredentialRefused(GitHubCredentialFailure.PROVIDER_UNAVAILABLE)
            issued = response.parsed_data
            expiry = _verify_issued_scope(issued, target, requested_permissions)
            # Account metadata needs an installation token; /user is not App identity.
            async with GitHub(
                issued.token,
                cache_strategy=cache,
                auto_retry=False,
                http_cache=False,
                follow_redirects=False,
                trust_env=False,
                timeout=_TIMEOUT_SECONDS,
            ) as token_client:
                account = await GitHubAccountDirectory(token_client).read(_BOT_LOGIN.format(slug=app.slug))
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
    except GitHubCredentialRefused as error:
        logger.warning(_REFUSAL_LOG, error.reason, assignment.app_id, target.repository_id)
        raise
    except (GitHubException, GitHubAccountLookupRefused, PyJWTError, TimeoutError, ValueError):
        # SDK/crypto exceptions can contain request headers or key/parser details.
        logger.warning(
            _REFUSAL_LOG, GitHubCredentialFailure.PROVIDER_UNAVAILABLE, assignment.app_id, target.repository_id
        )
        raise GitHubCredentialRefused(GitHubCredentialFailure.PROVIDER_UNAVAILABLE) from None
    finally:
        await cache.acleanup()
