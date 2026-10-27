"""GraphQL comment queries and the comment values built from GitHub's REST replies."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from githubkit.exception import GitHubException
from httpx import HTTPError

from teleclaude.core.workflow_store.github_io_fields import GitHubField
from teleclaude.core.workflow_store.github_io_models import GitHubComment
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.types.github_account import GitHubAccountKind, github_app_bot_login

_EMPTY = ""

__all__ = [
    "COMMENT_EDIT_QUERY",
    "COMMENT_NODES_QUERY",
    "COMMENT_QUERY",
    "EDIT_HISTORY_QUERY",
    "RECENT_COMMENTS_QUERY",
    "GraphIssueComment",
    "GraphRepository",
    "account_login",
    "comment_from_graph",
    "complete_bot_history",
    "read_one_comment",
    "written_comment",
]

EDIT_HISTORY_QUERY = """query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
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
COMMENT_EDIT_QUERY = """query($id:ID!, $before:String) { node(id:$id) { ... on IssueComment {
  userContentEdits(last:100, before:$before) { nodes { editor { __typename login } editedAt diff deletedAt }
    pageInfo { hasPreviousPage startCursor } } } } }"""
COMMENT_QUERY = """query($id:ID!) { node(id:$id) { ... on IssueComment { id databaseId body
  author { __typename login } editor { __typename login } lastEditedAt } } }"""
RECENT_COMMENTS_QUERY = """query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$repo) {
    issue(number:$number) {
      comments(last:100, before:$cursor) {
        nodes { id databaseId body author { __typename login } editor { __typename login } lastEditedAt
        }
        pageInfo { hasPreviousPage startCursor }
      }
    }
  }
}"""
COMMENT_NODES_QUERY = """query($ids:[ID!]!) { nodes(ids:$ids) { ... on IssueComment { id databaseId body
  author { __typename login } editor { __typename login } lastEditedAt } } }"""


def written_comment(rest_comment: Any, body: str) -> GitHubComment:
    """The comment GitHub just accepted, from its own reply: the bot wrote it and no one has edited it since."""
    user = rest_comment.user
    return GitHubComment(
        node_id=str(rest_comment.node_id),
        database_id=int(rest_comment.id),
        body=body,
        author=user.login if user is not None else None,
        editor=None,
        edit_history=(),
        history_complete=True,
        updated_at=rest_comment.updated_at,
    )


_GraphActor = TypedDict("_GraphActor", {"login": str, "__typename": str}, total=False)


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


class GraphIssueComment(TypedDict, total=False):
    id: str
    databaseId: int
    body: str
    author: _GraphActor | None
    editor: _GraphActor | None
    userContentEdits: _GraphEditConnection


class GraphIssueComments(TypedDict, total=False):
    nodes: list[GraphIssueComment]
    pageInfo: _GraphPageInfo


class _GraphIssue(TypedDict, total=False):
    comments: GraphIssueComments


class GraphRepository(TypedDict, total=False):
    issue: _GraphIssue | None


def comment_from_graph(node: GraphIssueComment) -> GitHubComment:
    author = node.get(GitHubField.AUTHOR)
    editor = node.get(GitHubField.EDITOR)
    database_id = node.get(GitHubField.DATABASE_ID)
    return GitHubComment(
        node_id=str(node.get(GitHubField.ID, _EMPTY)),
        database_id=database_id if isinstance(database_id, int) else 0,
        body=str(node.get(GitHubField.BODY) or _EMPTY),
        author=account_login(author),
        editor=account_login(editor),
        edit_history=(),
        history_complete=True,
    )


def account_login(actor: object) -> str | None:
    """Normalize a GraphQL actor login to GitHub's REST account presentation."""
    if not isinstance(actor, dict):
        return None
    login = actor.get(GitHubField.LOGIN)
    if not isinstance(login, str):
        return None
    if actor.get(GitHubField.TYPENAME) == GitHubAccountKind.BOT:
        return github_app_bot_login(login)
    return login


async def complete_bot_history(client: Any, comment: GitHubComment, bot_login: str) -> GitHubComment:
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
            COMMENT_EDIT_QUERY,
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
            editor_login = account_login(provider_edit.get(GitHubField.EDITOR))
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


async def read_one_comment(client: Any, node_id: str) -> GitHubComment:
    try:
        result = await client.graphql.arequest(COMMENT_QUERY, {GitHubField.ID: node_id})
        node = result.get(GitHubField.NODE)
        if not isinstance(node, dict):
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
        return comment_from_graph(cast(GraphIssueComment, node))
    except (GitHubException, HTTPError, TimeoutError, OSError):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE) from None
