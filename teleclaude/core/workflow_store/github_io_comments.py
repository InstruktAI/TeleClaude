"""GraphQL comment queries and the comment values built from GitHub's replies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from teleclaude.core.workflow_store.github_io_models import GitHubComment

__all__ = [
    "COMMENT_EDIT_QUERY",
    "COMMENT_QUERY",
    "EDIT_HISTORY_QUERY",
    "RECENT_COMMENTS_QUERY",
    "graph_time",
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
RECENT_COMMENTS_QUERY = """query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$repo) {
    issue(number:$number) {
      comments(last:100, before:$cursor) {
        nodes { id databaseId body createdAt author { __typename login } editor { __typename login } lastEditedAt
        }
        pageInfo { hasPreviousPage startCursor }
      }
    }
  }
}"""
COMMENT_EDIT_QUERY = """query($id:ID!, $before:String) { node(id:$id) { ... on IssueComment {
  userContentEdits(last:100, before:$before) { nodes { editor { __typename login } editedAt diff deletedAt }
    pageInfo { hasPreviousPage startCursor } } } } }"""
COMMENT_QUERY = """query($id:ID!) { node(id:$id) { ... on IssueComment { id databaseId body
  author { __typename login } editor { __typename login } lastEditedAt } } }"""


def graph_time(value: object) -> datetime | None:
    """A GraphQL timestamp as an aware datetime, or ``None`` when it is absent or malformed."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def written_comment(rest_comment: Any, body: str) -> GitHubComment:
    """The comment GitHub just accepted, taken from its own reply: the bot wrote it and no one has edited it since."""
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
