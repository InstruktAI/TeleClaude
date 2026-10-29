"""Provider transport shared by every workflow-store GitHub request: credentials, client call, refusals."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError
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
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_REFUSALS = (400, 401, 403, 422)
_RETRY_AFTER_HEADER = "retry-after"
_RATE_LIMIT_REMAINING_HEADER = "x-ratelimit-remaining"
_RATE_LIMIT_RESET_HEADER = "x-ratelimit-reset"
_RATE_LIMIT_EXHAUSTED = "0"
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
    ISSUE_ARTIFACTS_UNAVAILABLE = "issue_artifacts_unavailable"
    AWAITING_REPUBLICATION = "awaiting_republication"


@asynccontextmanager
async def _request_gate() -> AsyncIterator[None]:
    """One provider request at a time, process-wide: held for a single wire request, never across several."""
    lock = shared_github_io_loop().request_lock
    if lock is None:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    async with lock:
        yield


def _connection_pool() -> httpx.AsyncHTTPTransport:
    """The I/O loop's pool, shared by every gated request so each reuses an open connection."""
    pool = shared_github_io_loop().connection_pool
    if pool is None:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    return pool


class GitHubIORefused(RuntimeError):
    """A bounded reason why one store operation could not reach GitHub."""

    def __init__(
        self, reason: GitHubIOFailure, *, detail: str | None = None, resume_at: datetime | None = None
    ) -> None:
        message = reason.value if detail is None else _REFUSAL_WITH_DETAIL.format(reason.value, detail)
        super().__init__(message)
        self.reason = reason
        self.resume_at = resume_at


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

        The client's transport takes the process-wide request gate for each wire request, never across the
        callback or the credential issuance, so GitHub sees one request at a time.
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
                TokenAuthStrategy(token.get_secret_value()),
                MemCacheStrategy(),
                request_gate=_request_gate,
                connection_pool=_connection_pool(),
            ) as client:
                return await request(client)
        except GitHubIORefused:
            raise
        except RateLimitExceeded as error:
            raise GitHubIORefused(GitHubIOFailure.RATE_LIMITED, resume_at=_resume_time(error)) from None
        except RequestFailed as error:
            detail = _request_refusal_detail(operation, error)
            if error.response.status_code == _HTTP_TOO_MANY_REQUESTS:
                raise GitHubIORefused(
                    GitHubIOFailure.RATE_LIMITED, detail=detail, resume_at=_resume_time(error)
                ) from None
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
            credential = await issue_github_installation_credential(
                assignment, self.scope, permissions, request_gate=_request_gate, connection_pool=_connection_pool()
            )
        except GitHubCredentialRefused:
            raise GitHubIORefused(GitHubIOFailure.CREDENTIAL_REFUSED) from None
        self._credentials[key] = (credential.token, credential.expires_at)
        return credential.token


def _resume_time(error: RequestFailed) -> datetime | None:
    """When GitHub says requests may resume: `retry-after`, else the reset time of an exhausted limit, else never."""
    headers = error.response.headers
    retry_after = headers.get(_RETRY_AFTER_HEADER)
    if retry_after is not None:
        try:
            return datetime.now(UTC) + timedelta(seconds=int(retry_after))
        except ValueError:
            return None
    reset = headers.get(_RATE_LIMIT_RESET_HEADER)
    if headers.get(_RATE_LIMIT_REMAINING_HEADER) == _RATE_LIMIT_EXHAUSTED and reset is not None:
        try:
            return datetime.fromtimestamp(int(reset), tz=UTC)
        except ValueError:
            return None
    return None


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


def failure_reason(error: Exception) -> str:
    """Name why a reflection failed: the bounded refusal reason, or the exception type for any other failure."""
    return error.reason.value if isinstance(error, GitHubIORefused) else type(error).__name__


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
