"""Record which GitHub Projects board is a repository's board and which computer sets it up.

One platform-opened issue per repository, closed as not planned, carries the board's entries: platform
comments appended and never edited. A computer claims the board's setup with
`[action:board-claim computer:<name>]` and records the board it made with `[action:board project:<number>]`.
The comment order of the issue orders the entries. The board issue holds no workflow record and its comments
no record or ledger marker, so a store that predates the board reads it as neither an item nor the ledger.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from teleclaude.core.workflow_store.github_io_models import GitHubComment, GitHubIssue
from teleclaude.core.workflow_store.github_ledger import trusted_body
from teleclaude.core.workflow_store.github_record import (
    CommentEnvelopeAction,
    CommentEnvelopeField,
    comment_envelope_fields,
    render_comment_envelope,
)

BOARD_ISSUE_TITLE = "TeleClaude board"
_BOARD_ISSUE_EXPLANATION = (
    "The platform records here which GitHub Projects board shows this repository's work and which computer "
    "sets it up. It writes these comments itself; an edit by anyone else is never read."
)
_LINE_BREAK = "\n"
_BLANK_LINE = _LINE_BREAK + _LINE_BREAK
_BOARD_ISSUE_UNVERIFIABLE = "board issue #{} holds an entry that is not the platform's last write"


class GitHubBoardRecordRefused(ValueError):
    """The board issue holds a platform comment whose last write cannot be recovered."""


@dataclass(frozen=True)
class BoardRecord:
    """What the board issue's entries say: the latest recorded board and the claim that holds its setup."""

    project_number: int | None
    holder: str | None


def render_board_envelope(repository_id: int) -> str:
    """Render the envelope that opens the board issue's body and the board's README."""
    return render_comment_envelope(
        (
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.BOARD),
            (CommentEnvelopeField.REPOSITORY, repository_id),
        )
    )


def render_board_issue_body(repository_id: int) -> str:
    """Render the body of the issue the platform opens to record the repository's board."""
    return render_board_envelope(repository_id) + _BLANK_LINE + _BOARD_ISSUE_EXPLANATION


def render_board_claim(computer: str) -> str:
    """Render the comment that claims the board's setup for a computer."""
    return render_comment_envelope(
        (
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.BOARD_CLAIM),
            (CommentEnvelopeField.COMPUTER, computer),
        )
    )


def render_board_entry(project_number: int) -> str:
    """Render the comment that records the board a computer made."""
    return render_comment_envelope(
        (
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.BOARD),
            (CommentEnvelopeField.PROJECT, project_number),
        )
    )


def lowest_board_issue(issues: Sequence[GitHubIssue], bot_login: str, repository_id: int) -> GitHubIssue | None:
    """Return the lowest-numbered board issue the platform App opened for this repository, if any.

    Two computers may each open one; every computer uses the lowest, and a claim on any other counts for nothing.
    """
    opening = render_board_envelope(repository_id)
    found = [
        issue
        for issue in issues
        if issue.creator == bot_login and issue.body.split(_LINE_BREAK, 1)[0].strip() == opening
    ]
    return min(found, key=lambda issue: issue.number) if found else None


def read_board_record(comments: Sequence[GitHubComment], bot_login: str, issue_number: int) -> BoardRecord:
    """Read the board issue's entries in comment order.

    The record is the latest board entry and the first claim after it. A platform comment whose last write
    cannot be recovered refuses the read; comments by anyone else are not entries.
    """
    project_number: int | None = None
    holder: str | None = None
    for comment in sorted(comments, key=lambda candidate: candidate.database_id):
        body = trusted_body(comment, bot_login)
        if body is None:
            if comment.author == bot_login:
                raise GitHubBoardRecordRefused(_BOARD_ISSUE_UNVERIFIABLE.format(issue_number))
            continue
        fields = comment_envelope_fields(body)
        action = fields.get(CommentEnvelopeField.ACTION)
        if action == CommentEnvelopeAction.BOARD:
            entry = _number(fields.get(CommentEnvelopeField.PROJECT))
            if entry is not None:
                project_number, holder = entry, None
        elif action == CommentEnvelopeAction.BOARD_CLAIM and holder is None:
            holder = fields.get(CommentEnvelopeField.COMPUTER)
    return BoardRecord(project_number=project_number, holder=holder)


def _number(value: str | None) -> int | None:
    return int(value) if value is not None and value.isascii() and value.isdecimal() else None
