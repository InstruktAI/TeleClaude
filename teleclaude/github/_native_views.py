"""Read the three bound conversational views through GitHubKit and render prose with explicit list completeness."""

from __future__ import annotations

import asyncio
from typing import TextIO
from urllib.parse import quote

import httpx
from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit.github import GitHub
from githubkit.rest.paginator import Paginator
from githubkit.typing import UnsetType
from githubkit.utils import UNSET
from githubkit_schemas.v2026_03_10.models import Issue, IssueComment, PullRequest, PullRequestReviewComment
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.github_identity import GitHubPostingContext, resolve_native_github_posting_context
from teleclaude.github._comment_results import comment_reference
from teleclaude.github._conversation_scope import requested_pr_scope
from teleclaude.github._pr_provider import verify_pr_membership
from teleclaude.github.accounts import GitHubRateLimitFacts
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.github.native import NativeReadKind, NativeViewRequest
from teleclaude.github.replies import _reference as review_comment_reference

_EMPTY = ""
_SLASH = "/"
_ABSENT = "-"
_GET = "GET"
_HTTPS = "https"
_HOST = "api.github.com"
_REQUEST = "request"
_PAGE = "page"
_PER_PAGE = "per_page"
_HUNDRED = "100"
_READ_SECONDS = 60.0
_ISSUE_ROOT = "/repos/{repository}/issues/{number}"
_PR_ROOT = "/repos/{repository}/pulls/{number}"
_COMMENTS = "/comments"
_API = "https://api.github.com"
_ISSUE_URL = "https://github.com/{repository}/issues/{number}"
_INVALID = "Native read no longer establishes the exact bound provider scope"
_PROGRESS = "Comments (traversal in progress):"
_COMPLETE = "Comments: complete."
_INCOMPLETE = "Read incomplete; any displayed comments are a partial list."
_UNAVAILABLE = "GitHub read unavailable."
_STATUS = "Provider status: {status}"
_DELAY = "Retry after seconds: {seconds}"
_ISSUE_TEXT = "Issue #{number}: {title}\nState: {state}\nURL: {url}\nAuthor: {author}\nCreated: {created}\nUpdated: {updated}\n\n{body}"
_PR_TEXT = "PR #{number}: {title}\nState: {state}\nURL: {url}\nAuthor: {author}\nBase: {base}\nHead: {head}\nHead SHA: {sha}\n\n{body}"
_COMMENT_TEXT = "\nComment {identifier}\nAuthor: {author}\nCreated: {created}\nUpdated: {updated}\n\n{body}"
_REVIEW_TEXT = "\nReview comment {identifier}\nReply to: {parent}\nAuthor: {author}\nCreated: {created}\nUpdated: {updated}\nPath: {path}\nLine: {line}\nOriginal line: {original_line}\nStart line: {start_line}\nOriginal start line: {original_start_line}\nSide: {side}\nStart side: {start_side}\nCommit: {commit}\nOriginal commit: {original_commit}\nReview ID: {review}\n\n{body}"
_ISSUE_PERMISSIONS: AppPermissionsType = {"issues": "read"}
_PR_PERMISSIONS: AppPermissionsType = {"pull_requests": "read"}


async def _current(context: GitHubPostingContext, view: NativeViewRequest) -> bool:
    if await resolve_native_github_posting_context() != context:
        return False
    if view.kind is NativeReadKind.ISSUE:
        return view.scope is None and view.number == context.target.issue_number
    if view.scope is None or view.number != view.scope.object.container_number:
        return False
    valid, scope = await requested_pr_scope(context, view.scope.object)
    return valid and scope is not None and scope.same_creation(view.scope)


class _ReadScope:
    """Confine SDK-owned pagination to the admitted GET paths; no custom page navigation."""

    def __init__(self, context: GitHubPostingContext, view: NativeViewRequest) -> None:
        self.context, self.view = context, view
        repository = _SLASH.join(quote(part, safe=_EMPTY) for part in context.target.repository.split(_SLASH))
        issue = _ISSUE_ROOT.format(repository=repository, number=view.number)
        pr = _PR_ROOT.format(repository=repository, number=view.number)
        self.root = issue if view.kind is NativeReadKind.ISSUE else pr
        self.list_path = (
            pr + _COMMENTS
            if view.kind is NativeReadKind.REVIEW_COMMENTS
            else issue + _COMMENTS
            if view.comments
            else None
        )
        self.seen: set[httpx.URL] = set()

    async def check_request(self, request: httpx.Request) -> None:
        url = request.url
        if (
            request.method != _GET
            or url.scheme != _HTTPS
            or url.host != _HOST
            or url.port not in (None, 443)
            or url.userinfo
            or url.fragment
            or url in self.seen
            or not await _current(self.context, self.view)
        ):
            raise ValueError(_INVALID)
        if url.path == self.root:
            if url.query:
                raise ValueError(_INVALID)
        else:
            params = dict(url.params.multi_items())
            if (
                url.path != self.list_path
                or len(params) != len(url.params.multi_items())
                or params.get(_PER_PAGE) != _HUNDRED
                or set(params) - {_PER_PAGE, _PAGE}
                or (
                    _PAGE in params
                    and (not params[_PAGE].isascii() or not params[_PAGE].isdecimal() or int(params[_PAGE]) <= 0)
                )
            ):
                raise ValueError(_INVALID)
        self.seen.add(url)


def _issue_text(data: Issue, context: GitHubPostingContext, number: int) -> str:
    if (
        data.id <= 0
        or data.number != number
        or data.url.casefold()
        != (_API + _ISSUE_ROOT.format(repository=context.target.repository, number=number)).casefold()
        or data.html_url.casefold() != _ISSUE_URL.format(repository=context.target.repository, number=number).casefold()
        or data.pull_request is not UNSET
    ):
        raise ValueError(_INVALID)
    return _ISSUE_TEXT.format(
        number=data.number,
        title=data.title,
        state=data.state,
        url=data.html_url,
        author=data.user.login if data.user is not None else _ABSENT,
        created=data.created_at.isoformat(),
        updated=data.updated_at.isoformat(),
        body=data.body if isinstance(data.body, str) else _EMPTY,
    )


def _pr_text(data: PullRequest) -> str:
    return _PR_TEXT.format(
        number=data.number,
        title=data.title,
        state=data.state,
        url=data.html_url,
        author=data.user.login,
        base=data.base.ref,
        head=data.head.ref,
        sha=data.head.sha,
        body=data.body if data.body is not None else _EMPTY,
    )


def _available(value: str | int | None | UnsetType) -> str:
    return _ABSENT if value is None or value is UNSET else str(value)


def _comment_text(data: IssueComment, context: GitHubPostingContext, number: int) -> str:
    comment_reference(data, context.target, container_number=number)
    return _COMMENT_TEXT.format(
        identifier=data.id,
        author=data.user.login if data.user is not None else _ABSENT,
        created=data.created_at.isoformat(),
        updated=data.updated_at.isoformat(),
        body=data.body if isinstance(data.body, str) else _EMPTY,
    )


def _review_text(data: PullRequestReviewComment, context: GitHubPostingContext, number: int) -> str:
    review_comment_reference(data, context, number)
    return _REVIEW_TEXT.format(
        identifier=data.id,
        parent=_available(data.in_reply_to_id),
        author=data.user.login,
        created=data.created_at.isoformat(),
        updated=data.updated_at.isoformat(),
        path=data.path,
        line=_available(data.line),
        original_line=_available(data.original_line),
        start_line=_available(data.start_line),
        original_start_line=_available(data.original_start_line),
        side=_available(data.side),
        start_side=_available(data.start_side),
        commit=data.commit_id,
        original_commit=data.original_commit_id,
        review=_available(data.pull_request_review_id),
        body=data.body,
    )


async def _read(
    client: GitHub[TokenAuthStrategy], context: GitHubPostingContext, view: NativeViewRequest, stdout: TextIO
) -> None:
    owner, repo = (quote(part, safe=_EMPTY) for part in context.target.repository.split(_SLASH))
    if view.kind is NativeReadKind.ISSUE:
        issue = await client.rest.issues.async_get(owner, repo, view.number)
        if issue.status_code != 200:
            raise ValueError(_INVALID)
        print(_issue_text(issue.parsed_data, context, view.number), file=stdout)
    else:
        pr = await client.rest.pulls.async_get(owner, repo, view.number)
        if view.scope is None or pr.status_code != 200:
            raise ValueError(_INVALID)
        verify_pr_membership(pr.parsed_data, context, view.scope)
        if view.kind is NativeReadKind.PR:
            print(_pr_text(pr.parsed_data), file=stdout)
    if not view.comments:
        return
    print(_PROGRESS, file=stdout)
    if view.kind is NativeReadKind.REVIEW_COMMENTS:
        reviews: Paginator[PullRequestReviewComment] = client.rest.paginate(
            client.rest.pulls.async_list_review_comments, owner=owner, repo=repo, pull_number=view.number, per_page=100
        )
        async for review_comment in reviews:
            print(_review_text(review_comment, context, view.number), file=stdout)
        if not reviews.finalized:
            raise ValueError(_INVALID)
    else:
        comments: Paginator[IssueComment] = client.rest.paginate(
            client.rest.issues.async_list_comments, owner=owner, repo=repo, issue_number=view.number, per_page=100
        )
        async for issue_comment in comments:
            print(_comment_text(issue_comment, context, view.number), file=stdout)
        if not comments.finalized:
            raise ValueError(_INVALID)


async def read_native_view(
    context: GitHubPostingContext, view: NativeViewRequest, stdout: TextIO, stderr: TextIO
) -> int:
    """Print verified bound context, never JSON or a partial list presented as complete."""
    try:
        if not await _current(context, view):
            raise ValueError(_INVALID)
        permissions = _ISSUE_PERMISSIONS if view.kind is NativeReadKind.ISSUE else _PR_PERMISSIONS
        credential = await issue_github_installation_credential(context.binding.assignment, context.target, permissions)
        guard = _ReadScope(context, view)
        cache = MemCacheStrategy()
        try:
            async with create_github_client(TokenAuthStrategy(credential.token.get_secret_value()), cache) as client:
                # Public SDK/httpx composition; pagination and all endpoint execution stay with GitHubKit.
                async with client.get_async_client() as http_client:
                    http_client.event_hooks[_REQUEST].append(guard.check_request)
                async with asyncio.timeout(_READ_SECONDS):
                    await _read(client, context, view, stdout)
                if not await _current(context, view):
                    raise ValueError(_INVALID)
        finally:
            await cache.acleanup()
    except asyncio.CancelledError:
        print(_INCOMPLETE, file=stdout)
        raise
    except GitHubCredentialRefused as error:
        print(_UNAVAILABLE, file=stderr)
        if error.rate_limit is not None:
            print(_STATUS.format(status=error.rate_limit.status_code), file=stderr)
            print(_DELAY.format(seconds=error.rate_limit.retry_after.total_seconds()), file=stderr)
        return 2
    except (GitHubException, httpx.HTTPError, OSError, ValueError, SQLAlchemyError, TimeoutError) as error:
        print(_INCOMPLETE, file=stdout)
        print(_UNAVAILABLE, file=stderr)
        if isinstance(error, RequestFailed):
            print(_STATUS.format(status=error.response.status_code), file=stderr)
        if isinstance(error, RateLimitExceeded):
            facts = GitHubRateLimitFacts.from_sdk(error)
            print(_DELAY.format(seconds=facts.retry_after.total_seconds()), file=stderr)
        return 2
    if view.comments:
        print(_COMPLETE, file=stdout)
    return 0
