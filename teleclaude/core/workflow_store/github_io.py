"""Serialize workflow-store GitHub traffic on one daemon-independent I/O loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import Future
from contextlib import asynccontextmanager
from datetime import datetime
from enum import StrEnum
from time import monotonic
from typing import Any, TypedDict, TypeVar, cast

from githubkit.exception import GitHubException, RequestFailed
from githubkit.utils import UNSET
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError

from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_io_models import GitHubComment, GitHubIssue, GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_runtime import GitHubMutationPacing, shared_github_io_loop
from teleclaude.core.workflow_store.github_io_transport import (
    GitHubIOFailure,
    GitHubIORefused,
    GitHubTransport,
    int_argument,
    split_repository,
)
from teleclaude.core.workflow_store.github_reflection import ISSUE_FIELD_PARTS, IssueReflection, ProjectionPart
from teleclaude.types.github_account import GitHubAccountKind, github_app_bot_login
from teleclaude.types.github_binding import GitHubActorAssignment

_EMPTY = ""
_PAGE_SIZE = 100
_WRITE_PERMISSIONS: AppPermissionsType = {"issues": "write"}
_ISSUE_COLOR = "ededed"
_LABEL_COLOR_PREFIX = "#"
_Result = TypeVar("_Result")
_PACED_WRITE_INTERVAL_S = 1.0


_GraphActor = TypedDict("_GraphActor", {"login": str, "__typename": str}, total=False)

__all__ = [
    "GitHubComment",
    "GitHubIssue",
    "GitHubMutationPacing",
    "GitHubOperation",
    "GitHubRepositoryScope",
    "GitHubWorkflowIO",
]


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
        nodes { id databaseId body author { __typename login } editor { __typename login } lastEditedAt
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""
_COMMENT_EDIT_QUERY = """query($id:ID!, $before:String) { node(id:$id) { ... on IssueComment {
  userContentEdits(last:100, before:$before) { nodes { editor { __typename login } editedAt diff deletedAt }
    pageInfo { hasPreviousPage startCursor } } } } }"""
_COMMENT_QUERY = """query($id:ID!) { node(id:$id) { ... on IssueComment { id databaseId body
  author { __typename login } editor { __typename login } lastEditedAt } } }"""


class GitHubOperation(StrEnum):
    """Closed set of provider operations used by sync and async callers."""

    OPEN_ISSUE = "open_issue"
    UPDATE_ISSUE = "update_issue"
    ENSURE_LABEL = "ensure_label"
    DELETE_LABEL = "delete_label"
    LIST_ISSUES = "list_issues"
    LIST_LABELS = "list_labels"
    GET_ISSUE = "get_issue"
    LIST_SUB_ISSUES = "list_sub_issues"
    ADD_SUB_ISSUE = "add_sub_issue"
    REMOVE_SUB_ISSUE = "remove_sub_issue"
    GET_PARENT = "get_parent"
    LIST_BLOCKED_BY = "list_blocked_by"
    ADD_BLOCKED_BY = "add_blocked_by"
    REMOVE_BLOCKED_BY = "remove_blocked_by"
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
    ASSIGNEES = "assignees"
    TYPE = "type"
    NAME = "name"
    COLOR = "color"
    DESCRIPTION = "description"
    SUB_ISSUE_ID = "sub_issue_id"
    REPLACE_PARENT = "replace_parent"
    ISSUE_ID = "issue_id"
    PULL_REQUEST = "pull_request"
    ID = "id"
    DATABASE_ID = "databaseId"
    TYPENAME = "__typename"
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
    MESSAGE = "message"


_IssueUpdate = dict[GitHubField, str | list[str] | None]


class GitHubWorkflowIO:
    """Provide serialized issue, label, comment and edit-history operations for one repository."""

    def __init__(self, repository: GitHubRepositoryIdentity, assignment: GitHubActorAssignment) -> None:
        self.repository = repository
        self.assignment = assignment
        self.scope = GitHubRepositoryScope(repository.repository_id, repository.repository)
        self._transport = GitHubTransport(self.scope)
        self._pacing_window: GitHubMutationPacing | None = None

    @property
    def paced(self) -> bool:
        """Whether a paced-mutation window (the GitHub store switch) is open on this IO."""
        return self._pacing_window is not None

    @asynccontextmanager
    async def paced_mutations(self) -> AsyncIterator[GitHubMutationPacing]:
        """Pace mutative requests during one migration without changing ordinary traffic."""
        window = GitHubMutationPacing(last_wait_ended=monotonic())
        self._pacing_window = window
        try:
            yield window
        finally:
            self._pacing_window = None

    async def async_open_issue(self, title: str, body: str) -> GitHubIssue:
        return cast(GitHubIssue, await self._call(GitHubOperation.OPEN_ISSUE, title, body))

    def open_issue(self, title: str, body: str) -> GitHubIssue:
        return cast(GitHubIssue, self._sync(GitHubOperation.OPEN_ISSUE, title, body))

    async def async_update_issue(
        self,
        number: int,
        *,
        title: str,
        body: str,
        state: str,
        state_reason: str,
        labels: list[str],
        issue_type: str | None,
        assignees: list[str],
    ) -> None:
        await self._call(
            GitHubOperation.UPDATE_ISSUE, number, title, body, state, state_reason, labels, issue_type, assignees
        )

    def update_issue(
        self,
        number: int,
        *,
        title: str,
        body: str,
        state: str,
        state_reason: str,
        labels: list[str],
        issue_type: str | None,
        assignees: list[str],
    ) -> None:
        self._sync(
            GitHubOperation.UPDATE_ISSUE, number, title, body, state, state_reason, labels, issue_type, assignees
        )

    def queue_reflection(
        self,
        number: int,
        issue_id: int,
        reflection: IssueReflection,
        changed_parts: frozenset[ProjectionPart],
    ) -> Future[Any]:
        """Queue issue reflection without blocking the daemon's committing loop."""
        return shared_github_io_loop().submit(self._serialized_reflection(number, issue_id, reflection, changed_parts))

    async def async_reflect_issue(
        self,
        number: int,
        issue_id: int,
        reflection: IssueReflection,
        changed_parts: frozenset[ProjectionPart],
    ) -> None:
        future = shared_github_io_loop().submit(
            self._serialized_reflection(number, issue_id, reflection, changed_parts)
        )
        await asyncio.wrap_future(future)

    async def _serialized_reflection(
        self,
        number: int,
        issue_id: int,
        reflection: IssueReflection,
        changed_parts: frozenset[ProjectionPart],
    ) -> None:
        io_loop = shared_github_io_loop()
        if io_loop.unit_lock is None:
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
        async with io_loop.unit_lock:
            if ProjectionPart.LABELS in changed_parts:
                for label in reflection.labels:
                    await self._ensure_label(label.name, label.color, label.description)
            if changed_parts.intersection(ISSUE_FIELD_PARTS):
                await self._update_issue(
                    number,
                    reflection.title,
                    reflection.body,
                    str(reflection.state),
                    str(reflection.state_reason),
                    [label.name for label in reflection.labels],
                    reflection.issue_type,
                    list(reflection.assignees),
                    changed_parts,
                )
            if ProjectionPart.PARENT in changed_parts:
                current_parent = await self._get_parent(number)
                if current_parent is not None and current_parent[1] != reflection.parent_issue_id:
                    await self._remove_sub_issue(current_parent[0], issue_id)
                if reflection.parent_issue_id is not None and (
                    current_parent is None or current_parent[1] != reflection.parent_issue_id
                ):
                    if reflection.parent_issue_number is None:
                        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
                    current_children = set(await self._list_sub_issues(reflection.parent_issue_number))
                    if issue_id not in current_children:
                        await self._add_sub_issue(reflection.parent_issue_number, issue_id, True)
            if ProjectionPart.BLOCKED_BY in changed_parts:
                current_dependencies = set(await self._list_dependencies_blocked_by(number))
                desired_dependencies = set(reflection.blocked_by_issue_ids)
                for issue_id_to_remove in sorted(current_dependencies - desired_dependencies):
                    await self._remove_dependency_blocked_by(number, issue_id_to_remove)
                for issue_id_to_add in sorted(desired_dependencies - current_dependencies):
                    await self._add_blocked_by_dependency(number, issue_id_to_add)

    async def async_ensure_label(self, name: str, color: str = _ISSUE_COLOR, description: str = _EMPTY) -> None:
        await self._call(GitHubOperation.ENSURE_LABEL, name, color, description)

    def ensure_label(self, name: str, color: str = _ISSUE_COLOR, description: str = _EMPTY) -> None:
        self._sync(GitHubOperation.ENSURE_LABEL, name, color, description)

    async def async_delete_label(self, name: str) -> None:
        await self._call(GitHubOperation.DELETE_LABEL, name)

    async def async_list_repository_labels(self) -> tuple[str, ...]:
        return cast(tuple[str, ...], await self._call(GitHubOperation.LIST_LABELS))

    async def async_list_sub_issues(self, number: int) -> tuple[int, ...]:
        return cast(tuple[int, ...], await self._call(GitHubOperation.LIST_SUB_ISSUES, number))

    async def async_add_sub_issue(self, number: int, sub_issue_id: int, *, replace_parent: bool) -> None:
        await self._call(GitHubOperation.ADD_SUB_ISSUE, number, sub_issue_id, replace_parent)

    async def async_remove_sub_issue(self, number: int, sub_issue_id: int) -> None:
        await self._call(GitHubOperation.REMOVE_SUB_ISSUE, number, sub_issue_id)

    async def async_list_dependencies_blocked_by(self, number: int) -> tuple[int, ...]:
        return cast(tuple[int, ...], await self._call(GitHubOperation.LIST_BLOCKED_BY, number))

    async def async_add_blocked_by_dependency(self, number: int, issue_id: int) -> None:
        await self._call(GitHubOperation.ADD_BLOCKED_BY, number, issue_id)

    async def async_remove_dependency_blocked_by(self, number: int, issue_id: int) -> None:
        await self._call(GitHubOperation.REMOVE_BLOCKED_BY, number, issue_id)

    async def async_list_issues(self, since: datetime | None = None) -> tuple[GitHubIssue, ...]:
        return cast(tuple[GitHubIssue, ...], await self._call(GitHubOperation.LIST_ISSUES, since))

    async def async_get_issue(self, number: int) -> GitHubIssue:
        return cast(GitHubIssue, await self._call(GitHubOperation.GET_ISSUE, number))

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
        future = shared_github_io_loop().submit(self._serialized_dispatch(operation, *arguments))
        return await asyncio.wrap_future(future)

    def _sync(self, operation: GitHubOperation, *arguments: object) -> Any:
        return shared_github_io_loop().submit(self._serialized_dispatch(operation, *arguments)).result()

    def call_sync_within(self, operation: GitHubOperation, timeout: float, *arguments: object) -> Any:
        """Run one operation for a sync caller, abandoning it when `timeout` seconds pass (raises TimeoutError)."""
        future = shared_github_io_loop().submit(self._serialized_dispatch(operation, *arguments))
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise

    async def _serialized_dispatch(self, operation: GitHubOperation, *arguments: object) -> Any:
        # Each request of the dispatch takes the request lock itself (`GitHubTransport.call`).
        return await self._dispatch(operation, *arguments)

    async def _dispatch(self, operation: GitHubOperation, *arguments: object) -> Any:
        return await _OPERATION_HANDLERS[operation](self, arguments)

    async def _with_client(self, operation: GitHubOperation, request: Callable[[Any], Awaitable[_Result]]) -> _Result:
        return await self._transport.call(self.assignment, _WRITE_PERMISSIONS, operation, request)

    async def _open_issue(self, title: str, body: str) -> GitHubIssue:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubIssue:
            await self._pace_mutation_start()
            response = await client.rest.issues.async_create(
                owner, repo, data={GitHubField.TITLE: title, GitHubField.BODY: body}
            )
            issue = response.parsed_data
            return GitHubIssue(issue.number, issue.id, issue.node_id, issue.user.login, issue.updated_at)

        return await self._with_client(GitHubOperation.OPEN_ISSUE, request)

    async def _update_issue(
        self,
        number: int,
        title: str,
        body: str,
        state: str,
        reason: str,
        labels: list[str],
        issue_type: str | None,
        assignees: list[str],
        changed_parts: frozenset[ProjectionPart],
    ) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await self._pace_mutation_start()
            data: _IssueUpdate = {}
            if ProjectionPart.TITLE in changed_parts:
                data[GitHubField.TITLE] = title
            if ProjectionPart.BODY in changed_parts:
                data[GitHubField.BODY] = body
            if ProjectionPart.STATE in changed_parts:
                data[GitHubField.STATE] = state
                data[GitHubField.STATE_REASON] = reason
            if ProjectionPart.LABELS in changed_parts:
                data[GitHubField.LABELS] = labels
            if ProjectionPart.ISSUE_TYPE in changed_parts:
                data[GitHubField.TYPE] = issue_type
            if ProjectionPart.ASSIGNEES in changed_parts:
                data[GitHubField.ASSIGNEES] = assignees
            provider_data: dict[str, str | list[str] | None] = {field.value: value for field, value in data.items()}
            await client.rest.issues.async_update(
                owner,
                repo,
                number,
                data=provider_data,
            )

        await self._with_client(GitHubOperation.UPDATE_ISSUE, request)

    async def _ensure_label(self, name: str, color: str, description: str) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            try:
                response = await client.rest.issues.async_get_label(owner, repo, name)
            except RequestFailed as error:
                if error.response.status_code != 404:
                    raise
                response = None
            provider_color = color.removeprefix(_LABEL_COLOR_PREFIX)
            if response is not None:
                label = response.parsed_data
                if label.color == provider_color and label.description == description:
                    return
                await self._pace_mutation_start()
                await client.rest.issues.async_update_label(
                    owner,
                    repo,
                    name,
                    data={GitHubField.COLOR: provider_color, GitHubField.DESCRIPTION: description},
                )
                return
            await self._pace_mutation_start()
            await client.rest.issues.async_create_label(
                owner,
                repo,
                data={
                    GitHubField.NAME: name,
                    GitHubField.COLOR: provider_color,
                    GitHubField.DESCRIPTION: description,
                },
            )

        await self._with_client(GitHubOperation.ENSURE_LABEL, request)

    async def _delete_label(self, name: str) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            try:
                await self._pace_mutation_start()
                await client.rest.issues.async_delete_label(owner, repo, name)
            except RequestFailed as error:
                if error.response.status_code == 404:
                    return
                raise

        await self._with_client(GitHubOperation.DELETE_LABEL, request)

    async def _list_issues(self, since: datetime | None) -> tuple[GitHubIssue, ...]:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[GitHubIssue, ...]:
            found: list[GitHubIssue] = []
            page = 1
            while True:
                response = await client.rest.issues.async_list_for_repo(
                    owner,
                    repo,
                    creator=self.assignment.actor.login,
                    state=GitHubField.ALL_STATES,
                    since=since if since is not None else UNSET,
                    per_page=_PAGE_SIZE,
                    page=page,
                )
                issues = response.parsed_data
                found.extend(
                    GitHubIssue(issue.number, issue.id, issue.node_id, issue.user.login, issue.updated_at)
                    for issue in issues
                    if getattr(issue, GitHubField.PULL_REQUEST, None) is None
                )
                if len(issues) < _PAGE_SIZE:
                    return tuple(found)
                page += 1

        return await self._with_client(GitHubOperation.LIST_ISSUES, request)

    async def _get_issue(self, number: int) -> GitHubIssue:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubIssue:
            response = await client.rest.issues.async_get(owner, repo, number)
            issue = response.parsed_data
            return GitHubIssue(issue.number, issue.id, issue.node_id, issue.user.login, issue.updated_at)

        return await self._with_client(GitHubOperation.GET_ISSUE, request)

    async def _list_repository_labels(self) -> tuple[str, ...]:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[str, ...]:
            names: list[str] = []
            page = 1
            while True:
                response = await client.rest.issues.async_list_labels_for_repo(
                    owner, repo, per_page=_PAGE_SIZE, page=page
                )
                labels = response.parsed_data
                names.extend(label.name for label in labels)
                if len(labels) < _PAGE_SIZE:
                    return tuple(names)
                page += 1

        return await self._with_client(GitHubOperation.LIST_LABELS, request)

    async def _list_sub_issues(self, number: int) -> tuple[int, ...]:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[int, ...]:
            issue_ids: list[int] = []
            page = 1
            while True:
                response = await client.rest.issues.async_list_sub_issues(
                    owner, repo, number, per_page=_PAGE_SIZE, page=page
                )
                issues = response.parsed_data
                issue_ids.extend(int(issue.id) for issue in issues)
                if len(issues) < _PAGE_SIZE:
                    return tuple(issue_ids)
                page += 1

        return await self._with_client(GitHubOperation.LIST_SUB_ISSUES, request)

    async def _get_parent(self, number: int) -> tuple[int, int] | None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[int, int]:
            response = await client.rest.issues.async_get_parent(owner, repo, number)
            parent = response.parsed_data
            return parent.number, parent.id

        try:
            return await self._with_client(GitHubOperation.GET_PARENT, request)
        except GitHubIORefused as error:
            if error.reason is GitHubIOFailure.NOT_FOUND:
                return None
            raise

    async def _add_sub_issue(self, number: int, sub_issue_id: int, replace_parent: bool) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await self._pace_mutation_start()
            await client.rest.issues.async_add_sub_issue(
                owner, repo, number, sub_issue_id=sub_issue_id, replace_parent=replace_parent
            )

        await self._with_client(GitHubOperation.ADD_SUB_ISSUE, request)

    async def _remove_sub_issue(self, number: int, sub_issue_id: int) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await self._pace_mutation_start()
            await client.rest.issues.async_remove_sub_issue(owner, repo, number, sub_issue_id=sub_issue_id)

        await self._with_client(GitHubOperation.REMOVE_SUB_ISSUE, request)

    async def _list_dependencies_blocked_by(self, number: int) -> tuple[int, ...]:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[int, ...]:
            issue_ids: list[int] = []
            page = 1
            while True:
                response = await client.rest.issues.async_list_dependencies_blocked_by(
                    owner, repo, number, per_page=_PAGE_SIZE, page=page
                )
                issues = response.parsed_data
                issue_ids.extend(int(issue.id) for issue in issues)
                if len(issues) < _PAGE_SIZE:
                    return tuple(issue_ids)
                page += 1

        return await self._with_client(GitHubOperation.LIST_BLOCKED_BY, request)

    async def _add_blocked_by_dependency(self, number: int, issue_id: int) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await self._pace_mutation_start()
            await client.rest.issues.async_add_blocked_by_dependency(owner, repo, number, issue_id=issue_id)

        await self._with_client(GitHubOperation.ADD_BLOCKED_BY, request)

    async def _remove_dependency_blocked_by(self, number: int, issue_id: int) -> None:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await self._pace_mutation_start()
            await client.rest.issues.async_remove_dependency_blocked_by(owner, repo, number, issue_id=issue_id)

        await self._with_client(GitHubOperation.REMOVE_BLOCKED_BY, request)

    async def _read_comments(self, number: int) -> tuple[GitHubComment, ...]:
        owner, repo = split_repository(self.repository.repository)

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

        return await self._with_client(GitHubOperation.READ_COMMENTS, request)

    async def _create_comment(self, number: int, body: str) -> GitHubComment:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubComment:
            await self._pace_mutation_start()
            response = await client.rest.issues.async_create_comment(owner, repo, number, data={GitHubField.BODY: body})
            comment = response.parsed_data
            return await _read_one_comment(client, comment.node_id)

        return await self._with_client(GitHubOperation.CREATE_COMMENT, request)

    async def _update_comment(self, comment_id: int, body: str) -> GitHubComment:
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubComment:
            await self._pace_mutation_start()
            response = await client.rest.issues.async_update_comment(
                owner, repo, comment_id, data={GitHubField.BODY: body}
            )
            return await _read_one_comment(client, response.parsed_data.node_id)

        return await self._with_client(GitHubOperation.UPDATE_COMMENT, request)

    async def _pace_mutation_start(self) -> None:
        window = self._pacing_window
        if window is None:
            return
        now = monotonic()
        delay = _PACED_WRITE_INTERVAL_S - (now - window.last_start) if window.last_start else 0.0
        if delay > 0:
            await asyncio.sleep(delay)
        window.last_start = monotonic()
        window.count += 1


async def _dispatch_open_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._open_issue(str(args[0]), str(args[1]))


async def _dispatch_update_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    labels = args[5]
    assignees = args[7]
    issue_type = args[6]
    if (
        not isinstance(labels, list)
        or any(not isinstance(label, str) for label in labels)
        or not isinstance(assignees, list)
        or any(not isinstance(assignee, str) for assignee in assignees)
        or (issue_type is not None and not isinstance(issue_type, str))
    ):
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    await io._update_issue(
        int_argument(args[0]),
        str(args[1]),
        str(args[2]),
        str(args[3]),
        str(args[4]),
        labels,
        issue_type,
        assignees,
        ISSUE_FIELD_PARTS,
    )


async def _dispatch_ensure_label(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    await io._ensure_label(str(args[0]), str(args[1]), str(args[2]))


async def _dispatch_delete_label(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    await io._delete_label(str(args[0]))


async def _dispatch_list_sub_issues(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._list_sub_issues(int_argument(args[0]))


async def _dispatch_add_sub_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    if not isinstance(args[2], bool):
        raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
    await io._add_sub_issue(int_argument(args[0]), int_argument(args[1]), args[2])


async def _dispatch_remove_sub_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    await io._remove_sub_issue(int_argument(args[0]), int_argument(args[1]))


async def _dispatch_list_blocked_by(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._list_dependencies_blocked_by(int_argument(args[0]))


async def _dispatch_add_blocked_by(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    await io._add_blocked_by_dependency(int_argument(args[0]), int_argument(args[1]))


async def _dispatch_remove_blocked_by(io: GitHubWorkflowIO, args: tuple[object, ...]) -> None:
    await io._remove_dependency_blocked_by(int_argument(args[0]), int_argument(args[1]))


async def _dispatch_list_issues(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    since = args[0] if isinstance(args[0], datetime) else None
    return await io._list_issues(since)


async def _dispatch_list_labels(io: GitHubWorkflowIO, _args: tuple[object, ...]) -> Any:
    return await io._list_repository_labels()


async def _dispatch_get_issue(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._get_issue(int_argument(args[0]))


async def _dispatch_read_comments(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._read_comments(int_argument(args[0]))


async def _dispatch_create_comment(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._create_comment(int_argument(args[0]), str(args[1]))


async def _dispatch_update_comment(io: GitHubWorkflowIO, args: tuple[object, ...]) -> Any:
    return await io._update_comment(int_argument(args[0]), str(args[1]))


_OPERATION_HANDLERS: dict[GitHubOperation, Callable[[GitHubWorkflowIO, tuple[object, ...]], Awaitable[Any]]] = {
    GitHubOperation.OPEN_ISSUE: _dispatch_open_issue,
    GitHubOperation.UPDATE_ISSUE: _dispatch_update_issue,
    GitHubOperation.ENSURE_LABEL: _dispatch_ensure_label,
    GitHubOperation.DELETE_LABEL: _dispatch_delete_label,
    GitHubOperation.LIST_ISSUES: _dispatch_list_issues,
    GitHubOperation.LIST_LABELS: _dispatch_list_labels,
    GitHubOperation.GET_ISSUE: _dispatch_get_issue,
    GitHubOperation.LIST_SUB_ISSUES: _dispatch_list_sub_issues,
    GitHubOperation.ADD_SUB_ISSUE: _dispatch_add_sub_issue,
    GitHubOperation.REMOVE_SUB_ISSUE: _dispatch_remove_sub_issue,
    GitHubOperation.LIST_BLOCKED_BY: _dispatch_list_blocked_by,
    GitHubOperation.ADD_BLOCKED_BY: _dispatch_add_blocked_by,
    GitHubOperation.REMOVE_BLOCKED_BY: _dispatch_remove_blocked_by,
    GitHubOperation.READ_COMMENTS: _dispatch_read_comments,
    GitHubOperation.CREATE_COMMENT: _dispatch_create_comment,
    GitHubOperation.UPDATE_COMMENT: _dispatch_update_comment,
}


def _comment_from_graph(node: _GraphIssueComment) -> GitHubComment:
    author = node.get(GitHubField.AUTHOR)
    editor = node.get(GitHubField.EDITOR)
    database_id = node.get(GitHubField.DATABASE_ID)
    return GitHubComment(
        node_id=str(node.get(GitHubField.ID, _EMPTY)),
        database_id=database_id if isinstance(database_id, int) else 0,
        body=str(node.get(GitHubField.BODY) or _EMPTY),
        author=_account_login(author),
        editor=_account_login(editor),
        edit_history=(),
        history_complete=True,
    )


def _account_login(actor: object) -> str | None:
    """Normalize a GraphQL actor login to GitHub's REST account presentation."""
    if not isinstance(actor, dict):
        return None
    login = actor.get(GitHubField.LOGIN)
    if not isinstance(login, str):
        return None
    if actor.get(GitHubField.TYPENAME) == GitHubAccountKind.BOT:
        return github_app_bot_login(login)
    return login


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
        provider_edits = cast(list[_GraphEdit], connection.get(GitHubField.NODES, []))
        edits: list[_GraphEdit] = []
        for provider_edit in reversed(provider_edits):
            editor_login = _account_login(provider_edit.get(GitHubField.EDITOR))
            edit = cast(
                _GraphEdit,
                {
                    **provider_edit,
                    GitHubField.EDITOR: {GitHubField.LOGIN: editor_login} if editor_login is not None else None,
                },
            )
            edits.append(edit)
        cursor = info.get(GitHubField.START_CURSOR)
        return tuple(edits), cursor if isinstance(cursor, str) else None, bool(info.get(GitHubField.HAS_PREVIOUS_PAGE))
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
