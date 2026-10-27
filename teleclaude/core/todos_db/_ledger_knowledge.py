"""What the working copy knows of the GitHub ledger's commit entries.

The ledger's commit entries are kept locally so a commit decision never rereads the ledger: the copy holds
every transaction it has seen committed, and the comment id up to which that knowledge is contiguous.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.orm import Session

__all__ = [
    "LEDGER_COMMIT_DDL",
    "LEDGER_COMMIT_TABLE",
    "LedgerKnowledgeField",
    "all_ledger_commits",
    "ledger_commit_known",
    "ledger_commits_through",
    "record_ledger_commits",
    "set_ledger_commits_through",
]

LEDGER_COMMIT_TABLE = "github_ledger_commit"
LEDGER_COMMIT_DDL = (
    "CREATE TABLE IF NOT EXISTS github_ledger_commit (transaction_id TEXT PRIMARY KEY, comment_id INTEGER NOT NULL)"
)


class LedgerKnowledgeField(StrEnum):
    """Columns and parameters this knowledge reads and writes."""

    TRANSACTION_ID = "transaction_id"
    COMMENT_ID = "comment_id"
    THROUGH = "ledger_commits_through"
    ITEM_ID = "item_id"


class _Sql(StrEnum):
    KNOWN = "SELECT 1 FROM github_ledger_commit WHERE transaction_id = :transaction_id"
    ALL = "SELECT transaction_id FROM github_ledger_commit"
    RECORD = (
        "INSERT OR IGNORE INTO github_ledger_commit(transaction_id, comment_id) VALUES (:transaction_id, :comment_id)"
    )
    THROUGH = "SELECT ledger_commits_through FROM github_repository WHERE singleton = 1"
    SET_THROUGH = "UPDATE github_repository SET ledger_commits_through = :ledger_commits_through WHERE singleton = 1"


def ledger_commit_known(session: Session, transaction_id: str) -> bool:
    """Whether this copy has seen the ledger record ``transaction_id`` as committed."""
    return session.execute(text(_Sql.KNOWN), {LedgerKnowledgeField.TRANSACTION_ID: transaction_id}).first() is not None


def all_ledger_commits(session: Session) -> set[str]:
    """Every transaction this copy has seen the ledger record as committed."""
    return {str(row[0]) for row in session.execute(text(_Sql.ALL))}


def record_ledger_commits(session: Session, entries: Iterable[tuple[str, int]]) -> None:
    """Remember committed transactions with the ledger comment that records each."""
    for transaction_id, comment_id in entries:
        session.execute(
            text(_Sql.RECORD),
            {LedgerKnowledgeField.TRANSACTION_ID: transaction_id, LedgerKnowledgeField.COMMENT_ID: comment_id},
        )


def ledger_commits_through(session: Session) -> int | None:
    """The ledger comment id up to which every commit entry is known, or ``None`` before the first full read."""
    row = session.execute(text(_Sql.THROUGH)).first()
    value = row[0] if row is not None else None
    return int(value) if value is not None else None


def set_ledger_commits_through(session: Session, comment_id: int) -> None:
    """Advance the contiguous ledger position after a read of every entry up to ``comment_id``."""
    session.execute(text(_Sql.SET_THROUGH), {LedgerKnowledgeField.THROUGH: str(comment_id)})
