"""Persist what the working copy knows of each item's pull request, as caches of GitHub.

Every value here is a cache of GitHub or a derivation of the record: a rebuilt working copy
starts empty and the pull request lookup restores it, so no rebuild step exists. The owed set
is kept apart from the issue's `github_owed_reflection`, because the issue reflection's
completion clears that row.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from teleclaude.core.dates import parse_iso_datetime

from ._write_admission import WRITE_ADMISSION_BUDGET_S, connect_admitted

_PULL_REQUEST_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_pull_request (item_id TEXT PRIMARY KEY, number INTEGER, digest TEXT, "
    "delivered_noted INTEGER NOT NULL DEFAULT 0)"
)
_REVIEW_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_pull_request_review (item_id TEXT NOT NULL, round INTEGER NOT NULL, "
    "commit_id TEXT NOT NULL, PRIMARY KEY(item_id, round))"
)
_OWED_TABLE_DDL = "CREATE TABLE IF NOT EXISTS github_owed_pull_request (item_id TEXT PRIMARY KEY)"
_INTERVAL_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_pull_request_interval (item_id TEXT NOT NULL, number INTEGER NOT NULL, "
    "opened_at TEXT NOT NULL, closed_at TEXT, PRIMARY KEY(item_id, number))"
)
_SELECT_INTERVALS_SQL = "SELECT number, opened_at, closed_at FROM github_pull_request_interval WHERE item_id = :item_id"
_SAVE_INTERVAL_SQL = (
    "INSERT INTO github_pull_request_interval(item_id, number, opened_at, closed_at) "
    "VALUES (:item_id, :number, :opened_at, :closed_at) "
    "ON CONFLICT(item_id, number) DO UPDATE SET opened_at = excluded.opened_at, closed_at = excluded.closed_at"
)
_SELECT_PULL_REQUEST_SQL = "SELECT number, digest, delivered_noted FROM github_pull_request WHERE item_id = :item_id"
_SELECT_REVIEWS_SQL = "SELECT round, commit_id FROM github_pull_request_review WHERE item_id = :item_id"
_SAVE_PULL_REQUEST_SQL = (
    "INSERT INTO github_pull_request(item_id, number, digest, delivered_noted) "
    "VALUES (:item_id, :number, :digest, :delivered_noted) "
    "ON CONFLICT(item_id) DO UPDATE SET number = excluded.number, digest = excluded.digest, "
    "delivered_noted = excluded.delivered_noted"
)
_SAVE_REVIEW_SQL = (
    "INSERT INTO github_pull_request_review(item_id, round, commit_id) VALUES (:item_id, :round, :commit_id) "
    "ON CONFLICT(item_id, round) DO UPDATE SET commit_id = excluded.commit_id"
)
_MARK_OWED_SQL = "INSERT OR IGNORE INTO github_owed_pull_request(item_id) VALUES (:item_id)"
_CLEAR_OWED_SQL = "DELETE FROM github_owed_pull_request WHERE item_id = :item_id"
_OWED_SQL = "SELECT item_id FROM github_owed_pull_request"
_ITEM_FOR_PULL_REQUEST_SQL = (
    "SELECT p.item_id FROM github_pull_request AS p JOIN todo AS t ON CAST(t.id AS TEXT) = p.item_id "
    "WHERE p.number = :number"
)
_Parameters = dict[str, str | int | None]
_ITEM_FOR_ISSUE_SQL = (
    "SELECT i.item_id FROM github_item AS i JOIN todo AS t ON CAST(t.id AS TEXT) = i.item_id "
    "WHERE i.issue_number = :number"
)


class PullRequestField(StrEnum):
    """Closed set of pull-request bookkeeping columns and SQL bind names."""

    ITEM_ID = "item_id"
    NUMBER = "number"
    DIGEST = "digest"
    DELIVERED_NOTED = "delivered_noted"
    ROUND = "round"
    COMMIT_ID = "commit_id"
    OPENED_AT = "opened_at"
    CLOSED_AT = "closed_at"


@dataclass(frozen=True)
class PullRequestInterval:
    """When one of an item's pull requests was open: from its opening, until its closing if it has closed."""

    opened_at: datetime
    closed_at: datetime | None


@dataclass
class PullRequestBookkeeping:
    """What is known to be on GitHub for one item: its pull request, last written digest and posted reviews.

    ``intervals`` holds every pull request the item has had, by number, because an item that is reopened gets a
    second one and the current number alone cannot say where an earlier moment belongs.
    """

    number: int | None = None
    digest: str | None = None
    delivered_noted: bool = False
    reviews: dict[int, str] = field(default_factory=dict)
    intervals: dict[int, PullRequestInterval] = field(default_factory=dict)


def initialize_pull_request_bookkeeping(connection: sqlite3.Connection) -> None:
    """Install pull-request bookkeeping beside the GitHub working-copy tables."""
    connection.execute(_PULL_REQUEST_TABLE_DDL)
    connection.execute(_REVIEW_TABLE_DDL)
    connection.execute(_OWED_TABLE_DDL)
    connection.execute(_INTERVAL_TABLE_DDL)


def pull_request_bookkeeping(session: Session, item_id: str) -> PullRequestBookkeeping:
    """Read one item's pull-request bookkeeping; an item without any reads as empty."""
    parameters = {PullRequestField.ITEM_ID.value: item_id}
    row = session.execute(text(_SELECT_PULL_REQUEST_SQL), parameters).mappings().first()
    reviews = {
        int(review[PullRequestField.ROUND]): str(review[PullRequestField.COMMIT_ID])
        for review in session.execute(text(_SELECT_REVIEWS_SQL), parameters).mappings().all()
    }
    intervals = pull_request_intervals(session, item_id)
    if row is None:
        return PullRequestBookkeeping(reviews=reviews, intervals=intervals)
    number = row[PullRequestField.NUMBER]
    digest = row[PullRequestField.DIGEST]
    return PullRequestBookkeeping(
        number=int(number) if isinstance(number, int) else None,
        digest=str(digest) if isinstance(digest, str) else None,
        delivered_noted=bool(row[PullRequestField.DELIVERED_NOTED]),
        reviews=reviews,
        intervals=intervals,
    )


def pull_request_intervals(session: Session, item_id: str) -> dict[int, PullRequestInterval]:
    """Read every pull request interval the working copy holds for one item, by pull request number."""
    found: dict[int, PullRequestInterval] = {}
    rows = session.execute(text(_SELECT_INTERVALS_SQL), {PullRequestField.ITEM_ID.value: item_id}).mappings().all()
    for row in rows:
        opened_at = parse_iso_datetime(row[PullRequestField.OPENED_AT])
        if opened_at is None:
            continue
        found[int(row[PullRequestField.NUMBER])] = PullRequestInterval(
            opened_at=opened_at, closed_at=parse_iso_datetime(row[PullRequestField.CLOSED_AT])
        )
    return found


def pull_request_open_at(intervals: Iterable[tuple[int, PullRequestInterval]], moment: datetime) -> int | None:
    """The number of the pull request that was open at ``moment``: opened at or before it and not yet closed."""
    for number, interval in sorted(intervals, key=lambda entry: entry[1].opened_at):
        if interval.opened_at <= moment and (interval.closed_at is None or moment < interval.closed_at):
            return number
    return None


def save_pull_request_bookkeeping(session: Session, item_id: str, known: PullRequestBookkeeping) -> None:
    """Record what GitHub is now known to hold for one item."""
    for statement, parameters in _write_statements(item_id, known):
        session.execute(text(statement), parameters)


def store_pull_request_bookkeeping(db_path: Path, item_id: str, known: PullRequestBookkeeping, *, owed: bool) -> None:
    """Record progress from a completion callback, outside any working-copy transaction.

    Runs on a thread no working-copy write depends on, and waits for the writer up to the admission budget.
    """
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        for statement, parameters in _write_statements(item_id, known):
            connection.execute(statement, parameters)
        connection.execute(_MARK_OWED_SQL if owed else _CLEAR_OWED_SQL, {PullRequestField.ITEM_ID.value: item_id})
        connection.commit()
    finally:
        connection.close()


def owed_pull_requests(session: Session) -> tuple[str, ...]:
    """Return the items whose pull request or reviews still need writing to GitHub."""
    return tuple(str(row[0]) for row in session.execute(text(_OWED_SQL)).all())


def mark_pull_request_owed(session: Session, item_id: str) -> None:
    """Record that the item's pull request must be written after this commit."""
    session.execute(text(_MARK_OWED_SQL), {PullRequestField.ITEM_ID.value: item_id})


def clear_pull_request_owed(session: Session, item_id: str) -> None:
    """Clear the owed marker once GitHub holds everything the record reflects."""
    session.execute(text(_CLEAR_OWED_SQL), {PullRequestField.ITEM_ID.value: item_id})


def work_item_for_number(session: Session, number: int) -> str | None:
    """Return the item an issue or pull request number belongs to on this computer, if any."""
    parameters = {PullRequestField.NUMBER.value: number}
    for statement in (_ITEM_FOR_ISSUE_SQL, _ITEM_FOR_PULL_REQUEST_SQL):
        row = session.execute(text(statement), parameters).first()
        if row is not None:
            return str(row[0])
    return None


def _write_statements(item_id: str, known: PullRequestBookkeeping) -> list[tuple[str, _Parameters]]:
    statements: list[tuple[str, _Parameters]] = [
        (
            _SAVE_PULL_REQUEST_SQL,
            {
                PullRequestField.ITEM_ID.value: item_id,
                PullRequestField.NUMBER.value: known.number,
                PullRequestField.DIGEST.value: known.digest,
                PullRequestField.DELIVERED_NOTED.value: int(known.delivered_noted),
            },
        )
    ]
    statements.extend(
        (
            _SAVE_INTERVAL_SQL,
            {
                PullRequestField.ITEM_ID.value: item_id,
                PullRequestField.NUMBER.value: number,
                PullRequestField.OPENED_AT.value: interval.opened_at.isoformat(),
                PullRequestField.CLOSED_AT.value: interval.closed_at.isoformat() if interval.closed_at else None,
            },
        )
        for number, interval in known.intervals.items()
    )
    statements.extend(
        (
            _SAVE_REVIEW_SQL,
            {
                PullRequestField.ITEM_ID.value: item_id,
                PullRequestField.ROUND.value: review_round,
                PullRequestField.COMMIT_ID.value: commit_id,
            },
        )
        for review_round, commit_id in known.reviews.items()
    )
    return statements
