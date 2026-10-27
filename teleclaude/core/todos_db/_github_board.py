"""Persist what the working copy knows of the project's GitHub board, as caches of GitHub.

Which board is the project's board is recorded on GitHub (the board issue's entries); everything here is
a cache of that record or of GitHub's own identities, rediscoverable by setup, so a rebuilt working copy
starts empty and no rebuild step exists. The tables are installed with `CREATE TABLE IF NOT EXISTS` and
seed no rows: an initialized copy opens without the writer, and an absent setup row means no board is known.
The owed set is kept apart from the issue's and the pull request's, so no failure of one holds back another.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from ._write_admission import WRITE_ADMISSION_BUDGET_S, connect_admitted

_SETUP_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_board_setup (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
    "board_issue_number INTEGER, project_number INTEGER, project_id TEXT, status_field_id TEXT, "
    "lane_option_ids TEXT, needs_you_field_id TEXT, needs_you_option_id TEXT, "
    "linked INTEGER NOT NULL DEFAULT 0, owed_cause TEXT)"
)
_ITEM_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_board_item (item_id TEXT PRIMARY KEY, board_item_id TEXT, digest TEXT)"
)
_OWED_TABLE_DDL = "CREATE TABLE IF NOT EXISTS github_owed_board_item (item_id TEXT PRIMARY KEY)"
_SELECT_SETUP_SQL = (
    "SELECT board_issue_number, project_number, project_id, status_field_id, lane_option_ids, "
    "needs_you_field_id, needs_you_option_id, linked, owed_cause FROM github_board_setup WHERE singleton = 1"
)
_SAVE_SETUP_SQL = (
    "INSERT INTO github_board_setup(singleton, board_issue_number, project_number, project_id, status_field_id, "
    "lane_option_ids, needs_you_field_id, needs_you_option_id, linked, owed_cause) "
    "VALUES (1, :board_issue_number, :project_number, :project_id, :status_field_id, :lane_option_ids, "
    ":needs_you_field_id, :needs_you_option_id, :linked, :owed_cause) "
    "ON CONFLICT(singleton) DO UPDATE SET board_issue_number = excluded.board_issue_number, "
    "project_number = excluded.project_number, project_id = excluded.project_id, "
    "status_field_id = excluded.status_field_id, lane_option_ids = excluded.lane_option_ids, "
    "needs_you_field_id = excluded.needs_you_field_id, needs_you_option_id = excluded.needs_you_option_id, "
    "linked = excluded.linked, owed_cause = excluded.owed_cause"
)
_SELECT_ITEM_SQL = "SELECT board_item_id, digest FROM github_board_item WHERE item_id = :item_id"
_SAVE_ITEM_SQL = (
    "INSERT INTO github_board_item(item_id, board_item_id, digest) VALUES (:item_id, :board_item_id, :digest) "
    "ON CONFLICT(item_id) DO UPDATE SET board_item_id = excluded.board_item_id, digest = excluded.digest"
)
_FORGET_ALL_ITEMS_SQL = "DELETE FROM github_board_item"
_MARK_OWED_SQL = "INSERT OR IGNORE INTO github_owed_board_item(item_id) VALUES (:item_id)"
_MARK_ALL_OWED_SQL = "INSERT OR IGNORE INTO github_owed_board_item(item_id) SELECT item_id FROM github_item"
_CLEAR_OWED_SQL = "DELETE FROM github_owed_board_item WHERE item_id = :item_id"
_OWED_SQL = "SELECT item_id FROM github_owed_board_item"
_Parameters = dict[str, str | int | None]


class BoardField(StrEnum):
    """Closed set of board bookkeeping columns and SQL bind names."""

    ITEM_ID = "item_id"
    BOARD_ITEM_ID = "board_item_id"
    DIGEST = "digest"
    BOARD_ISSUE_NUMBER = "board_issue_number"
    PROJECT_NUMBER = "project_number"
    PROJECT_ID = "project_id"
    STATUS_FIELD_ID = "status_field_id"
    LANE_OPTION_IDS = "lane_option_ids"
    NEEDS_YOU_FIELD_ID = "needs_you_field_id"
    NEEDS_YOU_OPTION_ID = "needs_you_option_id"
    LINKED = "linked"
    OWED_CAUSE = "owed_cause"


@dataclass(frozen=True)
class BoardTargets:
    """The identities a board item write addresses: the project, the Status lanes and the Needs you marker."""

    project_id: str
    status_field_id: str
    lane_option_ids: Mapping[str, str]
    needs_you_field_id: str
    needs_you_option_id: str


@dataclass(frozen=True)
class BoardSetup:
    """What is known of the project's board: where it is recorded, its identities and what setup still owes."""

    board_issue_number: int | None = None
    project_number: int | None = None
    project_id: str | None = None
    status_field_id: str | None = None
    lane_option_ids: Mapping[str, str] = field(default_factory=dict)
    needs_you_field_id: str | None = None
    needs_you_option_id: str | None = None
    linked: bool = False
    owed_cause: str | None = None

    def targets(self) -> BoardTargets | None:
        """Return the identities item writes address, or None while the project or a field is not yet known."""
        if (
            self.project_id is None
            or self.status_field_id is None
            or not self.lane_option_ids
            or self.needs_you_field_id is None
            or self.needs_you_option_id is None
        ):
            return None
        return BoardTargets(
            project_id=self.project_id,
            status_field_id=self.status_field_id,
            lane_option_ids=self.lane_option_ids,
            needs_you_field_id=self.needs_you_field_id,
            needs_you_option_id=self.needs_you_option_id,
        )


@dataclass(frozen=True)
class BoardItemBookkeeping:
    """What is known to be on the board for one item: its board item and the last written digest."""

    board_item_id: str | None = None
    digest: str | None = None


def initialize_board_bookkeeping(connection: sqlite3.Connection) -> None:
    """Install board bookkeeping beside the GitHub working-copy tables."""
    connection.execute(_SETUP_TABLE_DDL)
    connection.execute(_ITEM_TABLE_DDL)
    connection.execute(_OWED_TABLE_DDL)


def board_setup(session: Session) -> BoardSetup:
    """Read the board setup cache; a copy that knows nothing of a board reads as the empty setup."""
    row = session.execute(text(_SELECT_SETUP_SQL)).first()
    return _setup_from_row(tuple(row)) if row is not None else BoardSetup()


def read_board_setup(db_path: Path) -> BoardSetup:
    """Read the board setup cache outside any working-copy transaction."""
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(_SELECT_SETUP_SQL).fetchone()
    finally:
        connection.close()
    return _setup_from_row(row) if row is not None else BoardSetup()


def store_board_setup(db_path: Path, setup: BoardSetup) -> None:
    """Record what setup learned or still owes, from the daemon's setup run.

    Runs on a thread no working-copy write depends on, and waits for the writer up to the admission budget.
    """
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        connection.execute(_SAVE_SETUP_SQL, _setup_parameters(setup))
        connection.commit()
    finally:
        connection.close()


def board_item_bookkeeping(session: Session, item_id: str) -> BoardItemBookkeeping:
    """Read one item's board bookkeeping; an item without any reads as empty."""
    row = session.execute(text(_SELECT_ITEM_SQL), {BoardField.ITEM_ID.value: item_id}).mappings().first()
    if row is None:
        return BoardItemBookkeeping()
    board_item_id = row[BoardField.BOARD_ITEM_ID]
    digest = row[BoardField.DIGEST]
    return BoardItemBookkeeping(
        board_item_id=str(board_item_id) if isinstance(board_item_id, str) else None,
        digest=str(digest) if isinstance(digest, str) else None,
    )


def store_board_item(db_path: Path, item_id: str, known: BoardItemBookkeeping, *, owed: bool) -> None:
    """Record one item's board progress from a completion callback or a repair.

    Runs on a thread no working-copy write depends on, and waits for the writer up to the admission budget.
    """
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        connection.execute(
            _SAVE_ITEM_SQL,
            {
                BoardField.ITEM_ID.value: item_id,
                BoardField.BOARD_ITEM_ID.value: known.board_item_id,
                BoardField.DIGEST.value: known.digest,
            },
        )
        connection.execute(_MARK_OWED_SQL if owed else _CLEAR_OWED_SQL, {BoardField.ITEM_ID.value: item_id})
        connection.commit()
    finally:
        connection.close()


def mark_board_item_owed_at(db_path: Path, item_id: str) -> None:
    """Record that the item's board item is owed again, from a completion callback whose write failed.

    Runs on a thread no working-copy write depends on, and waits for the writer up to the admission budget.
    """
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        connection.execute(_MARK_OWED_SQL, {BoardField.ITEM_ID.value: item_id})
        connection.commit()
    finally:
        connection.close()


def forget_board_items(db_path: Path) -> None:
    """Forget every cached board item, after setup recorded a board that is not the one they belonged to.

    Runs on a thread no working-copy write depends on, and waits for the writer up to the admission budget.
    """
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        connection.execute(_FORGET_ALL_ITEMS_SQL)
        connection.commit()
    finally:
        connection.close()


def owed_board_items(session: Session) -> tuple[str, ...]:
    """Return the items whose board item still needs writing to GitHub."""
    return tuple(str(row[0]) for row in session.execute(text(_OWED_SQL)).all())


def mark_board_item_owed(session: Session, item_id: str) -> None:
    """Record that the item's board item must be written after this commit."""
    session.execute(text(_MARK_OWED_SQL), {BoardField.ITEM_ID.value: item_id})


def mark_all_board_items_owed(session: Session) -> None:
    """Record that every item the project holds owes its board item."""
    session.execute(text(_MARK_ALL_OWED_SQL))


def mark_all_board_items_owed_at(db_path: Path) -> None:
    """Record that every item the project holds owes its board item, from the daemon's setup run.

    Runs on a thread no working-copy write depends on, and waits for the writer up to the admission budget.
    """
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        connection.execute(_MARK_ALL_OWED_SQL)
        connection.commit()
    finally:
        connection.close()


def clear_board_item_owed(session: Session, item_id: str) -> None:
    """Clear the owed marker once GitHub holds everything the record reflects."""
    session.execute(text(_CLEAR_OWED_SQL), {BoardField.ITEM_ID.value: item_id})


def _setup_from_row(row: Sequence[object]) -> BoardSetup:
    """Decode a row selected in `_SELECT_SETUP_SQL` column order."""
    (
        issue_number,
        project_number,
        project_id,
        status_field_id,
        lane_options,
        needs_field,
        needs_option,
        linked,
        cause,
    ) = row
    lane_option_ids = _text(lane_options)
    return BoardSetup(
        board_issue_number=_number(issue_number),
        project_number=_number(project_number),
        project_id=_text(project_id),
        status_field_id=_text(status_field_id),
        lane_option_ids=json.loads(lane_option_ids) if lane_option_ids is not None else {},
        needs_you_field_id=_text(needs_field),
        needs_you_option_id=_text(needs_option),
        linked=bool(linked),
        owed_cause=_text(cause),
    )


def _setup_parameters(setup: BoardSetup) -> _Parameters:
    return {
        BoardField.BOARD_ISSUE_NUMBER.value: setup.board_issue_number,
        BoardField.PROJECT_NUMBER.value: setup.project_number,
        BoardField.PROJECT_ID.value: setup.project_id,
        BoardField.STATUS_FIELD_ID.value: setup.status_field_id,
        BoardField.LANE_OPTION_IDS.value: json.dumps(dict(setup.lane_option_ids), sort_keys=True),
        BoardField.NEEDS_YOU_FIELD_ID.value: setup.needs_you_field_id,
        BoardField.NEEDS_YOU_OPTION_ID.value: setup.needs_you_option_id,
        BoardField.LINKED.value: int(setup.linked),
        BoardField.OWED_CAUSE.value: setup.owed_cause,
    }


def _number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
