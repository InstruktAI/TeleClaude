"""Read exact bound PR/ref facts using the established SDK and public pagination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from urllib.parse import quote

import httpx
from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.github import GitHub
from githubkit.rest.paginator import Paginator
from githubkit_schemas.v2026_03_10.models import GitRef, PullRequest, PullRequestSimple

from teleclaude.core.github_identity import GitHubPostingContext
from teleclaude.github.credentials import GitHubInstallationCredential
from teleclaude.types.github_posting import GitHubObjectAssociation, GitHubObjectKind, GitHubObjectRef
from teleclaude.types.github_publication import GitHubPullRequestSnapshot

_UTF8 = "utf-8"
_EMPTY = ""
_SLASH = "/"
_HOST = "api.github.com"
_HTTPS = "https"
_GET = "GET"
_REQUEST = "request"
_HEAD = "head"
_STATE = "state"
_ALL: Final = "all"
_PAGE = "page"
_PER_PAGE = "per_page"
_HUNDRED = "100"
_OPEN: Final = "open"
_CLOSED: Final = "closed"
_API_ROOT = "/repos/{repository}/pulls"
_REF_ROOT = "/repos/{repository}/git/ref/heads/{branch}"
_API_PR = "https://api.github.com/repos/{repository}/pulls/{number}"
_WEB_PR = "https://github.com/{repository}/pull/{number}"
_HEADS = "heads/"
_FULL_HEADS = "refs/heads/"
_COMMIT = "commit"
_COLON = ":"
_INVALID = "PR observations do not establish exact bound repository, branch, author and head"
_READ_SECONDS = 10.0
_DISCOVERY_SECONDS = 30.0
_MAX_DISCOVERY_PAGES = 10


@dataclass(frozen=True)
class PullRequestDiscovery:
    """One complete observed branch page set and its current ref inside the same finite phase."""

    numbers: tuple[int, ...]
    head: str


def prose_digest(value: str) -> str:
    """Hash opaque artifact prose without interpretation or comment envelopes."""
    return sha256(value.encode(_UTF8)).hexdigest()


def pr_reference(data: PullRequest, context: GitHubPostingContext) -> GitHubObjectRef:
    """Retain available scoped object facts even when subsequent author/text verification fails."""
    target = context.target
    if (
        data.id <= 0
        or data.number <= 0
        or data.base.repo.id != target.repository_id
        or data.base.repo.full_name.casefold() != target.repository.casefold()
        or data.url.casefold() != _API_PR.format(repository=target.repository, number=data.number).casefold()
    ):
        raise ValueError(_INVALID)
    return GitHubObjectRef(
        repository_id=target.repository_id,
        container_number=data.number,
        kind=GitHubObjectKind.PULL_REQUEST,
        provider_id=data.id,
    )


def verify_pr(data: PullRequest, context: GitHubPostingContext, head_sha: str) -> GitHubPullRequestSnapshot:
    """Verify provider authorship and current PR coordinates; neither author nor head is review authority."""
    target, actor = context.target, context.binding.assignment.actor
    ref = pr_reference(data, context)
    if (
        data.head.repo is None
        or data.head.repo.id != target.repository_id
        or data.head.repo.full_name.casefold() != target.repository.casefold()
        or data.head.ref != target.branch
        or data.base.ref != target.base
        or data.head.sha != head_sha
        or data.user.id != actor.id
        or data.user.node_id != actor.node_id
        or data.user.type != actor.type.value
        or not isinstance(data.draft, bool)
        or data.state not in (_OPEN, _CLOSED)
        or data.html_url.casefold() != _WEB_PR.format(repository=target.repository, number=data.number).casefold()
        or data.updated_at.utcoffset() is None
    ):
        raise ValueError(_INVALID)
    return GitHubPullRequestSnapshot(
        object=ref,
        head_ref=data.head.ref,
        base_ref=data.base.ref,
        head_sha=data.head.sha,
        title_digest=prose_digest(data.title),
        body_digest=prose_digest(data.body if data.body is not None else _EMPTY),
        state=_OPEN if data.state == _OPEN else _CLOSED,
        draft=data.draft,
        url=data.html_url,
        updated_at=data.updated_at.isoformat(),
    )


def verify_pr_membership(data: PullRequest, context: GitHubPostingContext, scope: GitHubObjectAssociation) -> None:
    """Conversation follows the recorded PR creator, independently of the current comment writer."""
    ref = pr_reference(data, context)
    creator = scope.actor
    if (
        ref != scope.object
        or scope.work_issue_number != context.target.issue_number
        or scope.pull_request is None
        or data.user.id != creator.id
        or data.user.node_id != creator.node_id
        or data.user.type != creator.type.value
        or data.html_url.casefold()
        != _WEB_PR.format(repository=context.target.repository, number=data.number).casefold()
    ):
        raise ValueError(_INVALID)


def _ref_sha(data: GitRef, ref: str) -> str:
    if data.ref != ref or data.object_.type != _COMMIT:
        raise ValueError(_INVALID)
    return data.object_.sha


class PullRequestReader:
    """Only exact-work-branch discovery, one explicit PR read, and its current remote head."""

    def __init__(self, credential: GitHubInstallationCredential) -> None:
        self.credential = credential
        self.owner, self.repository = (quote(part, safe=_EMPTY) for part in credential.target.repository.split(_SLASH))
        branch = credential.target.branch
        self.branch = branch
        self.root = _API_ROOT.format(repository=credential.target.repository)
        self.ref_root = _REF_ROOT.format(repository=credential.target.repository, branch=branch) if branch else None
        self.head_filter = credential.target.repository.split(_SLASH)[0] + _COLON + branch if branch else None
        self.number: int | None = None
        self.discovery: set[httpx.URL] | None = None

    async def check_request(self, request: httpx.Request) -> None:
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
        if url.path == self.ref_root or (self.number is not None and url.path == self.root + _SLASH + str(self.number)):
            if url.query:
                raise ValueError(_INVALID)
            return
        params = dict(url.params.multi_items())
        if (
            url.path != self.root
            or self.discovery is None
            or url in self.discovery
            or len(self.discovery) >= _MAX_DISCOVERY_PAGES
            or len(params) != len(url.params.multi_items())
            or params.get(_HEAD) != self.head_filter
            or params.get(_STATE) != _ALL
            or params.get(_PER_PAGE) != _HUNDRED
            or set(params) - {_HEAD, _STATE, _PER_PAGE, _PAGE}
            or (
                _PAGE in params
                and (not params[_PAGE].isascii() or not params[_PAGE].isdecimal() or int(params[_PAGE]) <= 0)
            )
        ):
            raise ValueError(_INVALID)
        self.discovery.add(url)

    async def discover(self, client: GitHub[TokenAuthStrategy]) -> PullRequestDiscovery:
        """Complete all-state branch discovery; a partial traversal never establishes absence."""
        if self.branch is None or self.head_filter is None:
            raise ValueError(_INVALID)
        self.discovery = set()
        try:
            async with asyncio.timeout(_DISCOVERY_SECONDS):
                paginator: Paginator[PullRequestSimple] = client.rest.paginate(
                    client.rest.pulls.async_list,
                    owner=self.owner,
                    repo=self.repository,
                    state=_ALL,
                    head=self.head_filter,
                    per_page=100,
                )
                found: dict[int, int] = {}
                async for data in paginator:
                    number, identifier = _discovered(data, self.credential)
                    if number in found or identifier in found.values():
                        raise ValueError(_INVALID)
                    found[number] = identifier
                if not paginator.finalized:
                    raise ValueError(_INVALID)
                return PullRequestDiscovery(tuple(found), await self.head(client))
        finally:
            self.discovery = None

    async def get(self, client: GitHub[TokenAuthStrategy], number: int) -> PullRequest:
        """Provider reads never use a last-PR/default-branch selector."""
        self.number = number
        try:
            response = await client.rest.pulls.async_get(self.owner, self.repository, number)
            if response.status_code != 200:
                raise ValueError(_INVALID)
            return _read_pr(response.parsed_data, number)
        finally:
            self.number = None

    async def head(self, client: GitHub[TokenAuthStrategy]) -> str:
        """Read the actual same-repository ref; absence is an unavailable push prerequisite."""
        branch = self.branch
        if not branch:
            raise ValueError(_INVALID)
        response = await client.rest.git.async_get_ref(self.owner, self.repository, quote(_HEADS + branch, safe=_EMPTY))
        if response.status_code != 200:
            raise ValueError(_INVALID)
        return _ref_sha(response.parsed_data, _FULL_HEADS + branch)


def _read_pr(data: PullRequest, number: int) -> PullRequest:
    if data.number != number:
        raise ValueError(_INVALID)
    return data


def _discovered(data: PullRequestSimple, credential: GitHubInstallationCredential) -> tuple[int, int]:
    target = credential.target
    if (
        data.id <= 0
        or data.number <= 0
        or data.head.ref != target.branch
        or data.head.repo is None
        or data.head.repo.id != target.repository_id
        or data.head.repo.full_name.casefold() != target.repository.casefold()
        or data.base.repo.id != target.repository_id
        or data.base.repo.full_name.casefold() != target.repository.casefold()
        or data.url.casefold() != _API_PR.format(repository=target.repository, number=data.number).casefold()
    ):
        raise ValueError(_INVALID)
    return data.number, data.id


@asynccontextmanager
async def pr_reader(
    credential: GitHubInstallationCredential,
) -> AsyncIterator[tuple[PullRequestReader, GitHub[TokenAuthStrategy]]]:
    """Use the existing SDK token/auth/client ownership, without a replacement transport or cache."""
    cache = MemCacheStrategy()
    reader = PullRequestReader(credential)
    try:
        async with GitHub(
            credential.token.get_secret_value(),
            cache_strategy=cache,
            auto_retry=False,
            http_cache=False,
            trust_env=False,
            follow_redirects=False,
            timeout=_READ_SECONDS,
            async_event_hooks={_REQUEST: [reader.check_request]},
        ) as client:
            yield reader, client
    finally:
        await cache.acleanup()
