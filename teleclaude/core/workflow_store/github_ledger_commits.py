"""The working copy's answer to whether the GitHub ledger records a transaction as committed."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from sqlalchemy.orm import Session

from teleclaude.core.todos_db._ledger_knowledge import (
    ledger_commit_known,
    ledger_commits_through,
    record_ledger_commits,
    set_ledger_commits_through,
)
from teleclaude.core.workflow_store.github_io_models import GitHubComment
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_record import (
    LedgerCommit,
    has_ledger_marker,
    parse_ledger_commit,
    trusted_comment_body,
)

__all__ = ["LedgerCommitView", "adopt_ledger_entries", "ledger_entries"]


def ledger_entries(comments: tuple[GitHubComment, ...], bot_login: str) -> list[tuple[str, int]]:
    """The committed transactions these ledger comments record, refusing a platform comment it cannot trust."""
    committed: list[tuple[str, int]] = []
    for comment in comments:
        trusted = trusted_comment_body(
            author=comment.author,
            editor=comment.editor,
            body=comment.body,
            edits=comment.edit_history,
            history_complete=comment.history_complete,
            bot_login=bot_login,
        )
        if trusted is None:
            if comment.author == bot_login:
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            continue
        if not has_ledger_marker(trusted):
            continue
        try:
            committed.append((parse_ledger_commit(trusted).transaction_id, comment.database_id))
        except ValueError:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED) from None
    return committed


class LedgerCommitView:
    """Whether the ledger records a transaction as committed, answered from the working copy's ledger knowledge.

    An unknown transaction first brings that knowledge up to date with the ledger comments newer than the
    position it is complete through, or with the whole ledger before the first read, once per view.
    """

    def __init__(
        self,
        session: Session,
        bot_login: str,
        read_ledger: Callable[[int | None], tuple[GitHubComment, ...]] | None,
    ) -> None:
        self._session = session
        self._bot_login = bot_login
        self._read_ledger = read_ledger
        self._caught_up = False

    def __contains__(self, transaction_id: object) -> bool:
        if not isinstance(transaction_id, str):
            return False
        if ledger_commit_known(self._session, transaction_id):
            return True
        if self._caught_up or self._read_ledger is None:
            return False
        self._caught_up = True
        comments = self._read_ledger(ledger_commits_through(self._session))
        record_ledger_commits(self._session, ledger_entries(comments, self._bot_login))
        if comments:
            set_ledger_commits_through(self._session, max(comment.database_id for comment in comments))
        return ledger_commit_known(self._session, transaction_id)


def adopt_ledger_entries(session: Session, entries: Iterable[tuple[LedgerCommit, GitHubComment]]) -> None:
    """Remember the commit entries of a contiguous ledger read and advance the position it is complete through."""
    read = [(entry.transaction_id, comment.database_id) for entry, comment in entries]
    record_ledger_commits(session, read)
    if read:
        set_ledger_commits_through(session, max(comment_id for _transaction_id, comment_id in read))
