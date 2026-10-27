"""Trust checks on the content a workflow record revision points at."""

from __future__ import annotations

from typing import Any

from teleclaude.core.workflow_store.github_io_models import GitHubComment
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_record import (
    ItemRevision,
    WorkflowField,
    join_content_comments,
    parse_content_comment,
    resolve_artifact_history,
    trusted_comment_body,
)

__all__ = ["validate_revision_content"]

_STATE_NAME = WorkflowField.STATE


def validate_revision_content(
    revision: ItemRevision, comments: list[GitHubComment] | tuple[GitHubComment, ...], bot_login: str
) -> None:
    """Refuse a revision whose referenced content comments are missing or have no recoverable bot version."""
    by_id = {comment.database_id: comment for comment in comments}
    pointers = [(name, pointer) for name, values in revision.artifacts.items() for pointer in values]
    if revision.state_content_pointer is not None:
        pointers.append((_STATE_NAME, revision.state_content_pointer))
    for name, pointer in pointers:
        if name != _STATE_NAME and pointer.head_comment_id is not None:
            try:
                history = resolve_artifact_history(
                    pointer,
                    revision.item_id,
                    name,
                    comments,
                    bot_login,
                )
            except ValueError:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
            if not history:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            continue
        parts: list[tuple[Any, str]] = []
        for comment_id in pointer.comment_ids:
            comment = by_id.get(comment_id)
            trusted = _trusted(comment, bot_login) if comment is not None else None
            if trusted is None:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            try:
                header, content = parse_content_comment(trusted)
            except ValueError:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
            if (
                header.item_id != revision.item_id
                or header.name != name
                or header.version != (pointer.remote_version_id or pointer.version)
                or header.digest != pointer.digest
            ):
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            parts.append((header, content))
        try:
            join_content_comments(parts)
        except ValueError:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None


def _trusted(comment: GitHubComment, bot_login: str) -> str | None:
    return trusted_comment_body(
        author=comment.author,
        editor=comment.editor,
        body=comment.body,
        edits=comment.edit_history,
        history_complete=comment.history_complete,
        bot_login=bot_login,
    )
