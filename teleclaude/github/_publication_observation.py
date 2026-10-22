"""Bound provider observations using the SDK's public cursor pagination."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit.github import GitHub
from githubkit_schemas.v2026_03_10.models import Activity, GitRef

from teleclaude.github.credentials import GitHubInstallationCredential

_HOST = "api.github.com"
_HTTPS = "https"
_GET = "GET"
_REQUEST = "request"
_SLASH = "/"
_EMPTY = ""
_HEADS = "refs/heads/"
_SHORT_HEADS = "heads/"
_REF_PATH = "/repos/{repository}/git/ref/heads/{branch}"
_ACTIVITY_PATH = "/repos/{repository}/activity"
_REF = "ref"
_DIRECTION = "direction"
_DESC = "desc"
_PER_PAGE = "per_page"
_HUNDRED = "100"
_CURSORS = frozenset({"before", "after"})
_FIXED_KEYS = frozenset({_REF, _DIRECTION, _PER_PAGE})
_MAX_PAGES = 10
_PHASE_SECONDS = 30.0
_REQUEST_SECONDS = 10.0
_COMMIT = "commit"
_INVALID = "Publication observation is incomplete or outside its exact bound scope"
_SHA = re.compile(r"[0-9a-f]{40}")


def _verified_ref(data: GitRef, expected: str) -> str:
    """Keep SDK response validation typed independently of its dynamic version selector."""
    if data.ref != expected or data.object_.type != _COMMIT or not _SHA.fullmatch(data.object_.sha):
        raise ValueError(_INVALID)
    return data.object_.sha


@dataclass(frozen=True)
class PublicationObservation:
    """A complete observed page set, never a causal receipt or atomic server snapshot."""

    head: str | None
    activities: tuple[Activity, ...]


class PublicationObservationRefused(ValueError):
    """Safe partial ref facts survive incomplete pagination without retaining raw SDK errors."""

    def __init__(
        self,
        head: str | None,
        observed: bool,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(_INVALID)
        self.head = head
        self.observed = observed
        self.status = status
        self.retry_after = retry_after


class PublicationObservationCancelled(asyncio.CancelledError):
    """Keep an already observed ref while preserving cancellation semantics."""

    def __init__(self, head: str | None, observed: bool) -> None:
        super().__init__()
        self.head = head
        self.observed = observed


class _PhaseScope:
    """Enforce this operation's budget and scope before the SDK sends any paginated request."""

    def __init__(self, repository: str, branch: str) -> None:
        self.ref_path = _REF_PATH.format(repository=repository, branch=branch)
        self.activity_path = _ACTIVITY_PATH.format(repository=repository)
        self.ref = _HEADS + branch
        self.pages: set[httpx.URL] = set()
        self.ref_reads = 0

    async def check(self, request: httpx.Request) -> None:
        url = request.url
        if (
            request.method != _GET
            or url.scheme != _HTTPS
            or url.host != _HOST
            or url.port not in (None, 443)
            or url.userinfo
            or url.fragment
        ):
            raise ValueError(_INVALID)
        if url.path == self.ref_path:
            if self.ref_reads or url.query:
                raise ValueError(_INVALID)
            self.ref_reads += 1
            return
        params = dict(url.params.multi_items())
        keys = set(params)
        if (
            url.path != self.activity_path
            or len(params) != len(url.params.multi_items())
            or params.get(_REF) != self.ref
            or params.get(_DIRECTION) != _DESC
            or params.get(_PER_PAGE) != _HUNDRED
            or not _FIXED_KEYS <= keys
            or keys - _FIXED_KEYS - _CURSORS
            or len(keys & _CURSORS) > 1
            or any(not params[key] for key in keys & _CURSORS)
            or len(self.pages) >= _MAX_PAGES
            or url in self.pages
        ):
            raise ValueError(_INVALID)
        self.pages.add(url)


async def observe_publication(
    credential: GitHubInstallationCredential,
    branch: str,
    *,
    before_send: bool,
) -> PublicationObservation:
    """Complete both fixed reads inside one deadline; busy/inconsistent history refuses, without polling."""
    scope = _PhaseScope(credential.target.repository, branch)
    owner, repository = (quote(part, safe=_EMPTY) for part in credential.target.repository.split(_SLASH))
    cache = MemCacheStrategy()
    observed_head: str | None = None
    head_observed = False
    try:
        async with (
            asyncio.timeout(_PHASE_SECONDS),
            GitHub(
                credential.token.get_secret_value(),
                cache_strategy=cache,
                auto_retry=False,
                http_cache=False,
                follow_redirects=False,
                trust_env=False,
                timeout=_REQUEST_SECONDS,
                async_event_hooks={_REQUEST: [scope.check]},
            ) as client,
        ):

            async def read_ref() -> str | None:
                nonlocal observed_head, head_observed
                try:
                    response = await client.rest.git.async_get_ref(
                        owner,
                        repository,
                        quote(_SHORT_HEADS + branch, safe=_EMPTY),
                    )
                except RequestFailed as error:
                    if error.response.status_code == 404:
                        head_observed = True
                        return None
                    raise
                if response.status_code != 200:
                    raise ValueError(_INVALID)
                observed_head = _verified_ref(response.parsed_data, scope.ref)
                head_observed = True
                return observed_head

            head = await read_ref() if before_send else None
            # Public SDK pagination follows provider Links/cursors, including empty intermediate pages.
            paginator = client.rest.paginate(
                client.rest.repos.async_list_activities,
                owner=owner,
                repo=repository,
                ref=scope.ref,
                direction=_DESC,
                per_page=100,
            )
            activities: dict[tuple[int, str], Activity] = {}
            async for activity in paginator:
                key = (activity.id, activity.node_id)
                if (
                    activity.ref != scope.ref
                    or activity.id <= 0
                    or not activity.node_id
                    or activity.timestamp.utcoffset() is None
                    or not _SHA.fullmatch(activity.before)
                    or not _SHA.fullmatch(activity.after)
                    or (key in activities and activities[key] != activity)
                    or any(existing[0] == key[0] or existing[1] == key[1] for existing in activities if existing != key)
                ):
                    raise ValueError(_INVALID)
                activities[key] = activity
            if not paginator.finalized:
                raise ValueError(_INVALID)
            if not before_send:
                head = await read_ref()
            return PublicationObservation(head, tuple(activities.values()))
    except asyncio.CancelledError:
        raise PublicationObservationCancelled(observed_head, head_observed) from None
    except (GitHubException, ValueError, TimeoutError) as error:
        status = error.response.status_code if isinstance(error, RequestFailed) else None
        retry_after = error.retry_after.total_seconds() if isinstance(error, RateLimitExceeded) else None
        raise PublicationObservationRefused(
            observed_head, head_observed, status=status, retry_after=retry_after
        ) from None
    finally:
        await cache.acleanup()
