"""Find and parse the repository-owned workflow ledger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from teleclaude.core.workflow_store.github_io import GitHubComment, GitHubIssue
from teleclaude.core.workflow_store.github_record import (
    LedgerCommit,
    has_ledger_marker,
    parse_ledger_commit,
    trusted_comment_body,
)

_LEDGER_UNVERIFIABLE = "workflow ledger issue #{} is unverifiable"
_LEDGER_INVALID = "workflow ledger issue #{} is invalid"
_LEDGER_DUPLICATE = "workflow repository has multiple ledger issues"


class GitHubLedgerRefused(ValueError):
    """The repository does not have one fully verifiable ledger."""


def find_ledger(
    comments_by_issue: Mapping[int, Sequence[GitHubComment]],
    issues_by_number: Mapping[int, GitHubIssue],
    bot_login: str,
) -> tuple[GitHubIssue | None, list[tuple[LedgerCommit, GitHubComment]]]:
    """Find the unique platform-authored ledger and all of its trusted entries."""
    entries: list[tuple[LedgerCommit, GitHubComment]] = []
    ledger_numbers: set[int] = set()
    for issue_number, comments in comments_by_issue.items():
        for comment in comments:
            commit = parse_ledger_comment(comment, bot_login, issue_number)
            if commit is not None:
                ledger_numbers.add(issue_number)
                entries.append((commit, comment))
    if len(ledger_numbers) > 1:
        raise GitHubLedgerRefused(_LEDGER_DUPLICATE)
    if not ledger_numbers:
        return None, entries
    ledger_number = next(iter(ledger_numbers))
    for comment in comments_by_issue[ledger_number]:
        if comment.author == bot_login and trusted_body(comment, bot_login) is None and has_ledger_marker(comment.body):
            raise GitHubLedgerRefused(_LEDGER_UNVERIFIABLE.format(ledger_number))
    return issues_by_number.get(ledger_number), entries


def parse_ledger_comment(comment: GitHubComment, bot_login: str, issue_number: int) -> LedgerCommit | None:
    """Parse a ledger entry only from its latest recoverable platform-authored body."""
    body = trusted_body(comment, bot_login)
    if body is None:
        if comment.author == bot_login and has_ledger_marker(comment.body):
            raise GitHubLedgerRefused(_LEDGER_UNVERIFIABLE.format(issue_number))
        return None
    if not has_ledger_marker(body):
        return None
    try:
        return parse_ledger_commit(body)
    except ValueError:
        raise GitHubLedgerRefused(_LEDGER_INVALID.format(issue_number)) from None


def trusted_body(comment: GitHubComment, bot_login: str) -> str | None:
    """Resolve one comment's latest platform-authored body."""
    return trusted_comment_body(
        author=comment.author,
        editor=comment.editor,
        body=comment.body,
        edits=comment.edit_history,
        history_complete=comment.history_complete,
        bot_login=bot_login,
    )
