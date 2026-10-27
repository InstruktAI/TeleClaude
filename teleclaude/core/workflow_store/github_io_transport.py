"""Provider transport shared by every workflow-store GitHub request: credentials, client call, refusals."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TypeVar
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError, Response
from instrukt_ai_logging import get_logger
from pydantic import SecretStr

from teleclaude.core.workflow_store.github_io_models import GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_runtime import shared_github_io_loop
from teleclaude.github.accounts import GitHubRateLimitFacts
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import (
    GitHubCredentialFailure,
    GitHubCredentialRefused,
    issue_github_installation_credential,
)
from teleclaude.github.rate_limit_headers import RateReading, named_resume_time, read_rate_reading
from teleclaude.types.github_binding import GitHubActorAssignment

logger = get_logger(__name__)

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
_HTTP_FORBIDDEN = 403
_SECONDARY_LIMIT_MESSAGE = "secondary rate limit"
_HTTP_REFUSALS = (400, 401, 403, 422)
_RATE_LIMIT_HOOK_FAILED_EVENT = "github_rate_limit_hook_failed"
_LOCK_WAIT_SECONDS = 30.0
_UNIT_SECONDS = 180.0
_LOCK_WAIT_DETAIL = "request lock wait exceeded"
_Result = TypeVar("_Result")
_CredentialKey = tuple[int, tuple[tuple[str, str], ...]]
_InstallationKey = tuple[int, str]


@dataclass(frozen=True)
class RateLimitSignal:
    """A limit response one installation received, and the time it names for requests to resume, if any."""

    app_id: int
    repository: str
    observed_at: datetime
    resume_at: datetime | None


type RateLimitHook = Callable[[RateLimitSignal], None]

_readings_lock = threading.Lock()
_latest_readings: dict[_InstallationKey, RateReading] = {}
_rate_limit_hook: RateLimitHook | None = None


def latest_rate_reading(app_id: int, repository: str) -> RateReading | None:
    """The budget the latest response to this App's installation on the repository left, if one was read."""
    with _readings_lock:
        return _latest_readings.get((app_id, repository))


def set_rate_limit_hook(hook: RateLimitHook | None) -> None:
    """Install, or with None remove, the one observer told of every limit response a transport receives.

    The hook runs on the GitHub I/O thread and must return promptly. A hook that raises is logged and changes
    nothing a transport does.
    """
    global _rate_limit_hook
    _rate_limit_hook = hook


def _signal_rate_limit(assignment: GitHubActorAssignment, repository: str, resume_at: datetime | None) -> None:
    hook = _rate_limit_hook
    if hook is None:
        return
    try:
        hook(RateLimitSignal(assignment.app_id, repository, datetime.now(UTC), resume_at))
    except Exception:  # supervision boundary: an observer must never change what a transport does
        logger.warning(_RATE_LIMIT_HOOK_FAILED_EVENT, exc_info=True)


def _record_reading(key: _InstallationKey, headers: Mapping[str, str]) -> None:
    reading = read_rate_reading(headers, datetime.now(UTC))
    if reading is None:
        return
    with _readings_lock:
        _latest_readings[key] = reading


class GitHubIOFailure(StrEnum):
    """Provider failures exposed without response bodies or credential data."""

    CREDENTIAL_REFUSED = "credential_refused"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    VALIDATION_REFUSED = "validation_refused"
    ROLE_UNMAPPED = "role_unmapped"


class GitHubIORefused(RuntimeError):
    """A bounded reason why one store operation could not reach GitHub."""

    def __init__(self, reason: GitHubIOFailure, *, detail: str | None = None) -> None:
        message = reason.value if detail is None else _REFUSAL_WITH_DETAIL.format(reason.value, detail)
        super().__init__(message)
        self.reason = reason


class GitHubTransport:
    """Issue and cache installation credentials per (App, permission set) and run client requests with them."""

    def __init__(self, scope: GitHubRepositoryScope, *, secondary_limit_is_rate_limit: bool = False) -> None:
        """``secondary_limit_is_rate_limit`` makes a secondary-limit response that names no delay a rate-limited
        refusal for this transport's callers; every other caller keeps the refusal it has always had for it."""
        self.scope = scope
        self._secondary_limit_is_rate_limit = secondary_limit_is_rate_limit
        self._credentials: dict[_CredentialKey, tuple[SecretStr, datetime]] = {}

    async def call(
        self,
        assignment: GitHubActorAssignment,
        permissions: AppPermissionsType,
        operation: StrEnum,
        request: Callable[[Any], Awaitable[_Result]],
    ) -> _Result:
        """Run one client request as the assigned App, mapping every provider failure to a bounded refusal."""
        installation: _InstallationKey = (assignment.app_id, self.scope.repository)

        async def observe(response: Response) -> None:
            _record_reading(installation, response.headers)

        try:
            token = await self._credential_token(assignment, permissions)
            async with create_github_client(
                TokenAuthStrategy(token.get_secret_value()), MemCacheStrategy(), response_observer=observe
            ) as client:
                return await request(client)
        except GitHubIORefused:
            raise
        except RateLimitExceeded as error:
            _signal_rate_limit(assignment, self.scope.repository, GitHubRateLimitFacts.from_sdk(error).resume_at)
            raise GitHubIORefused(GitHubIOFailure.RATE_LIMITED) from None
        except RequestFailed as error:
            if _is_secondary_limit(error):
                _signal_rate_limit(
                    assignment, self.scope.repository, named_resume_time(error.response.headers, datetime.now(UTC))
                )
                if self._secondary_limit_is_rate_limit:
                    raise GitHubIORefused(GitHubIOFailure.RATE_LIMITED) from None
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
            credential = await issue_github_installation_credential(assignment, self.scope, permissions)
        except GitHubCredentialRefused as error:
            if error.reason is GitHubCredentialFailure.RATE_LIMITED:
                resume_at = error.rate_limit.resume_at if error.rate_limit is not None else None
                _signal_rate_limit(assignment, self.scope.repository, resume_at)
            raise GitHubIORefused(GitHubIOFailure.CREDENTIAL_REFUSED) from None
        self._credentials[key] = (credential.token, credential.expires_at)
        return credential.token


def _is_secondary_limit(error: RequestFailed) -> bool:
    """Whether a refused request is GitHub's documented secondary-limit response.

    GitHub answers 403 or 429 with a message that says a secondary rate limit was exceeded, and need not name a
    delay; the SDK raises its rate-limit error only when a retry header or an exhausted quota supplies one.
    """
    status = error.response.status_code
    if status == _HTTP_TOO_MANY_REQUESTS:
        return True
    if status != _HTTP_FORBIDDEN:
        return False
    try:
        payload: object = error.response.json()
    except ValueError:
        return False
    message = payload.get(_MESSAGE_FIELD) if isinstance(payload, dict) else None
    return isinstance(message, str) and _SECONDARY_LIMIT_MESSAGE in message.lower()


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


async def run_serialized_unit[Result](work: Callable[[], Awaitable[Result]], *, unit_detail: str) -> Result:
    """Run one unit of GitHub requests while holding the process-wide request lock, within bounded waits.

    Every GitHub request the workflow store makes runs inside such a unit, so no two requests are ever in flight
    at once and a stuck unit cannot hold the lock for ever.
    """
    io_loop = shared_github_io_loop()
    if io_loop.request_lock is None:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    try:
        await asyncio.wait_for(io_loop.request_lock.acquire(), _LOCK_WAIT_SECONDS)
    except TimeoutError:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_LOCK_WAIT_DETAIL) from None
    try:
        async with asyncio.timeout(_UNIT_SECONDS):
            return await work()
    except TimeoutError:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=unit_detail) from None
    finally:
        io_loop.request_lock.release()
