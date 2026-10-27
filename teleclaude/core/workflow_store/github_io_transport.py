"""Provider transport shared by every workflow-store GitHub request: credentials, client call, refusals."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TypeVar
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import AsyncBaseTransport, AsyncHTTPTransport, HTTPError, Request, Response
from pydantic import SecretStr

from teleclaude.core.workflow_store.github_io_models import GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_runtime import shared_github_io_loop
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.types.github_binding import GitHubActorAssignment

_EMPTY = ""
_TOKEN_REFRESH_MARGIN = timedelta(minutes=2)
_REPOSITORY_SEPARATOR = "/"
_GITHUB_MESSAGE_LIMIT = 256
_HTTP_REFUSAL_DETAIL = "{} returned HTTP {}"
_HTTP_REFUSAL_WITH_MESSAGE = "{}: {}"
_REFUSAL_WITH_DETAIL = "{}: {}"
_MESSAGE_FIELD = "message"
_HTTP_NOT_FOUND = 404
_HTTP_REFUSALS = (400, 401, 403, 422)
_Result = TypeVar("_Result")
_CredentialKey = tuple[int, tuple[tuple[str, str], ...]]


class GitHubIOFailure(StrEnum):
    """Provider failures exposed without response bodies or credential data."""

    CREDENTIAL_REFUSED = "credential_refused"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    VALIDATION_REFUSED = "validation_refused"
    ROLE_UNMAPPED = "role_unmapped"


def _request_lock() -> asyncio.Lock:
    lock = shared_github_io_loop().request_lock
    if lock is None:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    return lock


class _SerializedTransport(AsyncBaseTransport):
    """Send each wire request under the process-wide request lock, releasing it once the response is read.

    The lock covers one provider request, so a caller that needs the next request waits behind at most the
    one in flight, however many requests the operation holding the client issues.
    """

    def __init__(self) -> None:
        self._wire = AsyncHTTPTransport()

    async def handle_async_request(self, request: Request) -> Response:
        async with _request_lock():
            response = await self._wire.handle_async_request(request)
            await response.aread()
        return response

    async def aclose(self) -> None:
        await self._wire.aclose()


class GitHubIORefused(RuntimeError):
    """A bounded reason why one store operation could not reach GitHub."""

    def __init__(self, reason: GitHubIOFailure, *, detail: str | None = None) -> None:
        message = reason.value if detail is None else _REFUSAL_WITH_DETAIL.format(reason.value, detail)
        super().__init__(message)
        self.reason = reason


class GitHubTransport:
    """Issue and cache installation credentials per (App, permission set) and run client requests with them."""

    def __init__(self, scope: GitHubRepositoryScope) -> None:
        self.scope = scope
        self._credentials: dict[_CredentialKey, tuple[SecretStr, datetime]] = {}

    async def call(
        self,
        assignment: GitHubActorAssignment,
        permissions: AppPermissionsType,
        operation: StrEnum,
        request: Callable[[Any], Awaitable[_Result]],
    ) -> _Result:
        """Run client requests as the assigned App, mapping every provider failure to a bounded refusal.

        The client's transport takes the process-wide request lock for each wire request, never across the
        callback, so GitHub sees one request at a time.
        """
        return await self._call(assignment, permissions, operation, request)

    async def _call(
        self,
        assignment: GitHubActorAssignment,
        permissions: AppPermissionsType,
        operation: StrEnum,
        request: Callable[[Any], Awaitable[_Result]],
    ) -> _Result:
        try:
            token = await self._credential_token(assignment, permissions)
            async with create_github_client(
                TokenAuthStrategy(token.get_secret_value()), MemCacheStrategy(), async_transport=_SerializedTransport()
            ) as client:
                return await request(client)
        except GitHubIORefused:
            raise
        except RateLimitExceeded:
            raise GitHubIORefused(GitHubIOFailure.RATE_LIMITED) from None
        except RequestFailed as error:
            detail = _request_refusal_detail(operation, error)
            if error.response.status_code == _HTTP_NOT_FOUND:
                raise GitHubIORefused(GitHubIOFailure.NOT_FOUND, detail=detail) from None
            if error.response.status_code in _HTTP_REFUSALS:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED, detail=detail) from None
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=detail) from None
        except (GitHubException, HTTPError, TimeoutError, OSError, ValueError, TypeError, AttributeError):
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE) from None

    async def _credential_token(self, assignment: GitHubActorAssignment, permissions: AppPermissionsType) -> SecretStr:
        key: _CredentialKey = (
            assignment.app_id,
            tuple(sorted((str(name), str(level)) for name, level in permissions.items())),
        )
        cached = self._credentials.get(key)
        if cached is not None and cached[1] > datetime.now(UTC) + _TOKEN_REFRESH_MARGIN:
            return cached[0]
        try:
            async with _request_lock():
                credential = await issue_github_installation_credential(assignment, self.scope, permissions)
        except GitHubCredentialRefused:
            raise GitHubIORefused(GitHubIOFailure.CREDENTIAL_REFUSED) from None
        self._credentials[key] = (credential.token, credential.expires_at)
        return credential.token


def _request_refusal_detail(operation: StrEnum, error: RequestFailed) -> str:
    detail = _HTTP_REFUSAL_DETAIL.format(operation.value, error.response.status_code)
    try:
        payload: object = error.response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get(_MESSAGE_FIELD)
        if isinstance(message, str):
            return _HTTP_REFUSAL_WITH_MESSAGE.format(detail, message[:_GITHUB_MESSAGE_LIMIT])
    return detail


def int_argument(value: object) -> int:
    """Validate one dispatched integer argument."""
    if not isinstance(value, int):
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    return value


def split_repository(value: str) -> tuple[str, str]:
    """Split `owner/name` into URL-safe parts."""
    owner, separator, repository = value.partition(_REPOSITORY_SEPARATOR)
    if not separator or not owner or not repository or _REPOSITORY_SEPARATOR in repository:
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    return quote(owner, safe=_EMPTY), quote(repository, safe=_EMPTY)
