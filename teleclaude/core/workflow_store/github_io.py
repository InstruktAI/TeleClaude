"""Serialize workflow-store GitHub traffic on one daemon-independent I/O loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TypedDict, TypeVar, cast
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError
from pydantic import SecretStr

from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.types.github_binding import GitHubActorAssignment

_EMPTY = ""
_PAGE_SIZE = 100
_TOKEN_REFRESH_MARGIN = timedelta(minutes=2)
_WRITE_PERMISSIONS: AppPermissionsType = {"issues": "write"}
_ISSUE_COLOR = "ededed"
_THREAD_NAME = "teleclaude-github-io"
_REPOSITORY_SEPARATOR = "/"
_Result = TypeVar("_Result")


class _GraphActor(TypedDict, total=False):
    login: str


class _GraphEdit(TypedDict, total=False):
    editor: _GraphActor | None
    editedAt: str | None
    diff: str | None
    deletedAt: str | None


class _GraphPageInfo(TypedDict, total=False):
    hasNextPage: bool
    hasPreviousPage: bool
    startCursor: str | None
    endCursor: str | None


class _GraphEditConnection(TypedDict, total=False):
    nodes: list[_GraphEdit]
    pageInfo: _GraphPageInfo


class _GraphIssueComment(TypedDict, total=False):
    id: str
    databaseId: int
    body: str
    author: _GraphActor | None
    editor: _GraphActor | None
    userContentEdits: _GraphEditConnection


class _GraphIssueComments(TypedDict, total=False):
    nodes: list[_GraphIssueComment]
    pageInfo: _GraphPageInfo


class _GraphIssue(TypedDict, total=False):
    comments: _GraphIssueComments


class _GraphRepository(TypedDict, total=False):
    issue: _GraphIssue | None


_EDIT_HISTORY_QUERY = """query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$repo) {
    issue(number:$number) {
      comments(first:100, after:$cursor) {
        nodes { id databaseId body author { login } editor { login } lastEditedAt
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""
_COMMENT_EDIT_QUERY = """query($id:ID!, $before:String) { node(id:$id) { ... on IssueComment {
  userContentEdits(last:100, before:$before) { nodes { editor { login } editedAt diff deletedAt }
    pageInfo { hasPreviousPage startCursor } } } } }"""
_COMMENT_QUERY = """query($id:ID!) { node(id:$id) { ... on IssueComment { id databaseId body
  author { login } editor { login } lastEditedAt } } }"""


class GitHubIOFailure(StrEnum):
    """Provider failures exposed without response bodies or credential data."""

    CREDENTIAL_REFUSED = "credential_refused"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    VALIDATION_REFUSED = "validation_refused"


class GitHubOperation(StrEnum):
    """Closed set of provider operations used by sync and async callers."""

    OPEN_ISSUE = "open_issue"
    UPDATE_ISSUE = "update_issue"
    ENSURE_LABEL = "ensure_label"
    LIST_ISSUES = "list_issues"
    READ_COMMENTS = "read_comments"
    CREATE_COMMENT = "create_comment"
    UPDATE_COMMENT = "update_comment"


class GitHubField(StrEnum):
    """Closed set of GitHub REST and GraphQL field names consumed by this adapter."""

    ISSUES = "issues"
    WRITE = "write"
    TITLE = "title"
    BODY = "body"
    STATE = "state"
    STATE_REASON = "state_reason"
    LABELS = "labels"
    NAME = "name"
    COLOR = "color"
    PULL_REQUEST = "pull_request"
    ID = "id"
    DATABASE_ID = "databaseId"
    AUTHOR = "author"
    EDITOR = "editor"
    LOGIN = "login"
    REPOSITORY = "repository"
    ISSUE = "issue"
    COMMENTS = "comments"
    PAGE_INFO = "pageInfo"
    HAS_NEXT_PAGE = "hasNextPage"
    END_CURSOR = "endCursor"
    START_CURSOR = "startCursor"
    USER_CONTENT_EDITS = "userContentEdits"
    NODES = "nodes"
    HAS_PREVIOUS_PAGE = "hasPreviousPage"
    LAST_EDITED_AT = "lastEditedAt"
    ALL_STATES = "all"
    NODE = "node"
    OWNER = "owner"
    REPO = "repo"
    NUMBER = "number"
    CURSOR = "cursor"
    BEFORE = "before"


class GitHubIORefused(RuntimeError):
    """A bounded reason why one store operation could not reach GitHub."""

    def __init__(self, reason: GitHubIOFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class GitHubRepositoryScope:
    """Repository-only scope used before a workflow item exists."""

    repository_id: int
    repository: str


@dataclass(frozen=True)
class GitHubComment:
    """Comment body and editor history needed to establish platform authorship."""

    node_id: str
    database_id: int
    body: str
    author: str | None
    editor: str | None
    edit_history: tuple[_GraphEdit, ...]
    history_complete: bool


@dataclass(frozen=True)
class GitHubIssue:
    """Issue facts required by store rebuild and reflection."""

    number: int
    node_id: str
    creator: str
    updated_at: datetime | None


class _GitHubIOLoop:
    """Own the single process loop used by every project's synchronous and async caller."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.request_lock: asyncio.Lock | None = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name=_THREAD_NAME, daemon=True)
        self.thread.start()
        self.ready.wait()

    def submit(self, coroutine: Any) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.request_lock = asyncio.Lock()
        self.ready.set()
        self.loop.run_forever()


_io_loop: _GitHubIOLoop | None = None
_io_loop_lock = threading.Lock()


def _shared_loop() -> _GitHubIOLoop:
    global _io_loop
    with _io_loop_lock:
        if _io_loop is None:
            _io_loop = _GitHubIOLoop()
        return _io_loop


class GitHubWorkflowIO:
    """Provide serialized issue, label, comment and edit-history operations for one repository."""

    def __init__(self, repository: GitHubRepositoryIdentity, assignment: GitHubActorAssignment) -> None:
        self.repository = repository
        self.assignment = assignment
        self.scope = GitHubRepositoryScope(repository.repository_id, repository.repository)
        self._credential: SecretStr | None = None
        self._expires_at: datetime | None = None

    async def async_open_issue(self, title: str, body: str) -> GitHubIssue:
        return cast(GitHubIssue, await self._call(GitHubOperation.OPEN_ISSUE, title, body))

    def open_issue(self, title: str, body: str) -> GitHubIssue:
        return cast(GitHubIssue, self._sync(GitHubOperation.OPEN_ISSUE, title, body))

    async def async_update_issue(
        self, number: int, *, title: str, body: str, state: str, state_reason: str, labels: list[str]
    ) -> None:
        await self._call(GitHubOperation.UPDATE_ISSUE, number, title, body, state, state_reason, labels)

    def update_issue(
        self, number: int, *, title: str, body: str, state: str, state_reason: str, labels: list[str]
    ) -> None:
        self._sync(GitHubOperation.UPDATE_ISSUE, number, title, body, state, state_reason, labels)

    def queue_reflection(
        self, number: int, *, title: str, body: str, state: str, state_reason: str, labels: list[str]
    ) -> Future[Any]:
        """Queue issue reflection without blocking the daemon's committing loop."""

        async def reflect() -> None:
            io_loop = _shared_loop()
            if io_loop.request_lock is None:
                raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
            async with io_loop.request_lock:
                for label in labels:
                    await self._ensure_label(label, _ISSUE_COLOR)
                await self._update_issue(number, title, body, state, state_reason, labels)

        return _shared_loop().submit(reflect())

    async def async_ensure_label(self, name: str, color: str = _ISSUE_COLOR) -> None:
        await self._call(GitHubOperation.ENSURE_LABEL, name, color)

    def ensure_label(self, name: str, color: str = _ISSUE_COLOR) -> None:
        self._sync(GitHubOperation.ENSURE_LABEL, name, color)

    async def async_list_issues(self, since: datetime | None = None) -> tuple[GitHubIssue, ...]:
        return cast(tuple[GitHubIssue, ...], await self._call(GitHubOperation.LIST_ISSUES, since))

    def list_issues(self, since: datetime | None = None) -> tuple[GitHubIssue, ...]:
        return cast(tuple[GitHubIssue, ...], self._sync(GitHubOperation.LIST_ISSUES, since))

    async def async_read_comments(self, number: int) -> tuple[GitHubComment, ...]:
        return cast(tuple[GitHubComment, ...], await self._call(GitHubOperation.READ_COMMENTS, number))

    def read_comments(self, number: int) -> tuple[GitHubComment, ...]:
        return cast(tuple[GitHubComment, ...], self._sync(GitHubOperation.READ_COMMENTS, number))

    async def async_create_comment(self, number: int, body: str) -> GitHubComment:
        return cast(GitHubComment, await self._call(GitHubOperation.CREATE_COMMENT, number, body))

    def create_comment(self, number: int, body: str) -> GitHubComment:
        return cast(GitHubComment, self._sync(GitHubOperation.CREATE_COMMENT, number, body))

    async def async_update_comment(self, comment_id: int, body: str) -> GitHubComment:
        return cast(GitHubComment, await self._call(GitHubOperation.UPDATE_COMMENT, comment_id, body))

    def update_comment(self, comment_id: int, body: str) -> GitHubComment:
        return cast(GitHubComment, self._sync(GitHubOperation.UPDATE_COMMENT, comment_id, body))

    async def _call(self, operation: GitHubOperation, *arguments: object) -> Any:
        future = _shared_loop().submit(self._serialized_dispatch(operation, *arguments))
        return await asyncio.wrap_future(future)

    def _sync(self, operation: GitHubOperation, *arguments: object) -> Any:
        return _shared_loop().submit(self._serialized_dispatch(operation, *arguments)).result()

    async def _serialized_dispatch(self, operation: GitHubOperation, *arguments: object) -> Any:
        io_loop = _shared_loop()
        if io_loop.request_lock is None:
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
        async with io_loop.request_lock:
            return await self._dispatch(operation, *arguments)

    async def _dispatch(self, operation: GitHubOperation, *arguments: object) -> Any:
        return await _OPERATION_HANDLERS[operation](self, arguments)

    async def _credential_token(self) -> SecretStr:
        if self._credential is not None and self._expires_at is not None:
            if self._expires_at > datetime.now(UTC) + _TOKEN_REFRESH_MARGIN:
                return self._credential
        try:
            credential = await issue_github_installation_credential(self.assignment, self.scope, _WRITE_PERMISSIONS)
        except GitHubCredentialRefused:
            raise GitHubIORefused(GitHubIOFailure.CREDENTIAL_REFUSED) from None
        self._credential = credential.token
        self._expires_at = credential.expires_at
        return credential.token

    async def _with_client(self, operation: Callable[[Any], Awaitable[_Result]]) -> _Result:
        try:
            token = await self._credential_token()
            async with create_github_client(TokenAuthStrategy(token.get_secret_value()), MemCacheStrategy()) as client:
                return await operation(client)
        except GitHubIORefused:
            raise
        except RateLimitExceeded:
            raise GitHubIORefused(GitHubIOFailure.RATE_LIMITED) from None
        except RequestFailed as error:
            if error.response.status_code == 404:
                raise GitHubIORefused(GitHubIOFailure.NOT_FOUND) from None
            if error.response.status_code in (400, 401, 403, 422):
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE) from None
        except (GitHubException, HTTPError, TimeoutError, OSError, ValueError, TypeError, AttributeError):
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE) from None

    async def _open_issue(self, title: str, body: str) -> GitHubIssue:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubIssue:
            response = await client.rest.issues.async_create(
                owner, repo, data={GitHubField.TITLE: title, GitHubField.BODY: body}
            )
            issue = response.parsed_data
            return GitHubIssue(issue.number, issue.node_id, issue.user.login, issue.updated_at)

        return await self._with_client(request)

    async def _update_issue(
        self, number: int, title: str, body: str, state: str, reason: str, labels: list[str]
    ) -> None:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await client.rest.issues.async_update(
                owner,
                repo,
                number,
                data={
                    GitHubField.TITLE: title,
                    GitHubField.BODY: body,
                    GitHubField.STATE: state,
                    GitHubField.STATE_REASON: reason,
                    GitHubField.LABELS: labels,
                },
            )

        await self._with_client(request)

    async def _ensure_label(self, name: str, color: str) -> None:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            try:
                await client.rest.issues.async_get_label(owner, repo, name)
                return
            except RequestFailed as error:
                if error.response.status_code != 404:
                    raise
            await client.rest.issues.async_create_label(
                owner, repo, data={GitHubField.NAME: name, GitHubField.COLOR: color}
            )

        await self._with_client(request)

    async def _list_issues(self, since: datetime | None) -> tuple[GitHubIssue, ...]:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[GitHubIssue, ...]:
            found: list[GitHubIssue] = []
            page = 1
            while True:
                response = await client.rest.issues.async_list_for_repo(
                    owner,
                    repo,
                    creator=self.assignment.actor.login,
                    state=GitHubField.ALL_STATES,
                    since=since,
                    per_page=_PAGE_SIZE,
                    page=page,
                )
                issues = response.parsed_data
                found.extend(
                    GitHubIssue(issue.number, issue.node_id, issue.user.login, issue.updated_at)
                    for issue in issues
                    if getattr(issue, GitHubField.PULL_REQUEST, None) is None
                )
                if len(issues) < _PAGE_SIZE:
                    return tuple(found)
                page += 1

        return await self._with_client(request)

    async def _read_comments(self, number: int) -> tuple[GitHubComment, ...]:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[GitHubComment, ...]:
            cursor: str | None = None
            comments: list[GitHubComment] = []
            while True:
                result = await client.graphql.arequest(
                    _EDIT_HISTORY_QUERY,
                    {
                        GitHubField.OWNER: owner,
                        GitHubField.REPO: repo,
                        GitHubField.NUMBER: number,
                        GitHubField.CURSOR: cursor,
                    },
                )
                repository_data = cast(_GraphRepository, result.get(GitHubField.REPOSITORY, {}))
                issue = repository_data.get(GitHubField.ISSUE)
                if not isinstance(issue, dict):
                    raise GitHubIORefused(GitHubIOFailure.NOT_FOUND)
                connection = issue.get(GitHubField.COMMENTS, {})
                for node in connection.get(GitHubField.NODES, []):
                    comment = _comment_from_graph(node)
                    if comment.editor is not None and comment.editor != self.assignment.actor.login:
                        comment = await _complete_bot_history(client, comment, self.assignment.actor.login)
                    comments.append(comment)
                page = connection.get(GitHubField.PAGE_INFO, {})
                if not page.get(GitHubField.HAS_NEXT_PAGE):
                    return tuple(comments)
                next_cursor = page.get(GitHubField.END_CURSOR)
                if not isinstance(next_cursor, str) or next_cursor == cursor:
                    raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
                cursor = next_cursor

        return await self._with_client(request)

    async def _create_comment(self, number: int, body: str) -> GitHubComment:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubComment:
            response = await client.rest.issues.async_create_comment(owner, repo, number, data={GitHubField.BODY: body})
            comment = response.parsed_data
            return await _read_one_comment(client, comment.node_id)

        return await self._with_client(request)

    async def _update_comment(self, comment_id: int, body: str) -> GitHubComment:
        owner, repo = _split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubComment:
            response = await client.rest.issues.async_update_comment(
                owner, repo, comment_id, data={GitHubField.BODY: body}
            )
            return await _read_one_comment(client, response.parsed_data.node_id)

        return await self._with_client(request)


async def _dispatch_open_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._open_issue(str(args[0]), str(args[1]))


async def _dispatch_update_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    labels = args[5]
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    await io._update_issue(_int_argument(args[0]), str(args[1]), str(args[2]), str(args[3]), str(args[4]), labels)


async def _dispatch_ensure_label(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    await io._ensure_label(str(args[0]), str(args[1]))


async def _dispatch_list_issues(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    since = args[0] if isinstance(args[0], datetime) else None
    return await io._list_issues(since)


async def _dispatch_read_comments(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._read_comments(_int_argument(args[0]))


async def _dispatch_create_comment(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._create_comment(_int_argument(args[0]), str(args[1]))


async def _dispatch_update_comment(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._update_comment(_int_argument(args[0]), str(args[1]))


_OPERATION_HANDLERS: dict[GitHubOperation, Callable[[GitHubWorkflowIO, tuple[object, ...]], Awaitable[Any]]] = {
    GitHubOperation.OPEN_ISSUE: _dispatch_open_issue,
    GitHubOperation.UPDATE_ISSUE: _dispatch_update_issue,
    GitHubOperation.ENSURE_LABEL: _dispatch_ensure_label,
    GitHubOperation.LIST_ISSUES: _dispatch_list_issues,
    GitHubOperation.READ_COMMENTS: _dispatch_read_comments,
    GitHubOperation.CREATE_COMMENT: _dispatch_create_comment,
    GitHubOperation.UPDATE_COMMENT: _dispatch_update_comment,
}


def _int_argument(value: object) -> int:
    if not isinstance(value, int):
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    return value


def _split_repository(value: str) -> tuple[str, str]:
    owner, separator, repository = value.partition(_REPOSITORY_SEPARATOR)
    if not separator or not owner or not repository or _REPOSITORY_SEPARATOR in repository:
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    return quote(owner, safe=_EMPTY), quote(repository, safe=_EMPTY)


def _comment_from_graph(node: _GraphIssueComment) -> GitHubComment:
    author = node.get(GitHubField.AUTHOR)
    editor = node.get(GitHubField.EDITOR)
    database_id = node.get(GitHubField.DATABASE_ID)
    return GitHubComment(
        node_id=str(node.get(GitHubField.ID, _EMPTY)),
        database_id=database_id if isinstance(database_id, int) else 0,
        body=str(node.get(GitHubField.BODY) or _EMPTY),
        author=author.get(GitHubField.LOGIN) if isinstance(author, dict) else None,
        editor=editor.get(GitHubField.LOGIN) if isinstance(editor, dict) else None,
        edit_history=(),
        history_complete=True,
    )


async def _complete_bot_history(client: Any, comment: GitHubComment, bot_login: str) -> GitHubComment:
    """Read edit pages newest-first until the latest platform edit is found."""
    edits: list[_GraphEdit] = []
    cursor: str | None = None
    while True:
        page = await _read_edit_page(client, comment.node_id, cursor)
        if page is None:
            return GitHubComment(
                comment.node_id, comment.database_id, comment.body, comment.author, comment.editor, tuple(edits), False
            )
        page_edits, next_cursor, has_previous = page
        found = False
        for edit in page_edits:
            edits.append(edit)
            editor = edit.get(GitHubField.EDITOR)
            if isinstance(editor, dict) and editor.get(GitHubField.LOGIN) == bot_login:
                found = True
                break
        if found:
            return GitHubComment(
                comment.node_id, comment.database_id, comment.body, comment.author, comment.editor, tuple(edits), True
            )
        if not has_previous:
            return GitHubComment(
                comment.node_id, comment.database_id, comment.body, comment.author, comment.editor, tuple(edits), True
            )
        if has_previous and (next_cursor is None or next_cursor == cursor):
            return GitHubComment(
                comment.node_id, comment.database_id, comment.body, comment.author, comment.editor, tuple(edits), False
            )
        cursor = next_cursor


async def _read_edit_page(
    client: Any, comment_node_id: str, before: str | None
) -> tuple[tuple[_GraphEdit, ...], str | None, bool] | None:
    try:
        result = await client.graphql.arequest(
            _COMMENT_EDIT_QUERY,
            {GitHubField.ID: comment_node_id, GitHubField.BEFORE: before},
        )
        node = result.get(GitHubField.NODE)
        if not isinstance(node, dict):
            return None
        connection = cast(_GraphEditConnection, node.get(GitHubField.USER_CONTENT_EDITS, {}))
        info = cast(_GraphPageInfo, connection.get(GitHubField.PAGE_INFO, {}))
        edits = tuple(reversed(cast(list[_GraphEdit], connection.get(GitHubField.NODES, []))))
        cursor = info.get(GitHubField.START_CURSOR)
        return edits, cursor if isinstance(cursor, str) else None, bool(info.get(GitHubField.HAS_PREVIOUS_PAGE))
    except (GitHubException, HTTPError, TimeoutError, OSError):
        return None


async def _read_one_comment(client: Any, node_id: str) -> GitHubComment:
    try:
        result = await client.graphql.arequest(_COMMENT_QUERY, {GitHubField.ID: node_id})
        node = result.get(GitHubField.NODE)
        if not isinstance(node, dict):
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
        return _comment_from_graph(cast(_GraphIssueComment, node))
    except (GitHubException, HTTPError, TimeoutError, OSError):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE) from None
