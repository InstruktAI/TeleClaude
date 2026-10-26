"""Persist what a computer has captured of its sessions' conversation until it is on GitHub, in the working copy.

Everything here is a cache of GitHub or a derivation of the runtime's transcripts, so a lost working copy loses
nothing that GitHub or the transcripts do not hold: the sessions' turns are captured again from the runtime, and the
position on each destination is read back from GitHub. Captured parts are already protected; no raw transcript
content is kept.

A turn is kept until its last comment is on GitHub and is then forgotten; the pointer per session remembers how far
the runtime's turns have been taken.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from teleclaude.core.dates import parse_iso_datetime

_TURN_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_conversation_turn (session_id TEXT NOT NULL, ordinal INTEGER NOT NULL, "
    "turn_identity TEXT NOT NULL, item_id TEXT NOT NULL, repository_id INTEGER NOT NULL, repository TEXT NOT NULL, "
    "destination_number INTEGER NOT NULL, app_id INTEGER NOT NULL, completed_at TEXT NOT NULL, "
    "captured_at TEXT NOT NULL, in_flight INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, ordinal))"
)
_PART_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_conversation_part (session_id TEXT NOT NULL, ordinal INTEGER NOT NULL, "
    "part INTEGER NOT NULL, body TEXT NOT NULL, posted INTEGER NOT NULL DEFAULT 0, "
    "PRIMARY KEY(session_id, ordinal, part))"
)
_POINTER_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS github_conversation_pointer (session_id TEXT PRIMARY KEY, last_identity TEXT NOT NULL, "
    "last_ordinal INTEGER NOT NULL)"
)
_START_TABLE_DDL = "CREATE TABLE IF NOT EXISTS github_conversation_start (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), started_at TEXT NOT NULL)"
_SELECT_POINTER_SQL = "SELECT last_identity, last_ordinal FROM github_conversation_pointer WHERE session_id = ?"
_SAVE_POINTER_SQL = (
    "INSERT INTO github_conversation_pointer(session_id, last_identity, last_ordinal) VALUES (?, ?, ?) "
    "ON CONFLICT(session_id) DO UPDATE SET last_identity = excluded.last_identity, last_ordinal = excluded.last_ordinal "
    "WHERE excluded.last_ordinal > github_conversation_pointer.last_ordinal"
)
_INSERT_TURN_SQL = (
    "INSERT OR IGNORE INTO github_conversation_turn(session_id, ordinal, turn_identity, item_id, repository_id, "
    "repository, destination_number, app_id, completed_at, captured_at, in_flight) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_INSERT_PART_SQL = (
    "INSERT OR IGNORE INTO github_conversation_part(session_id, ordinal, part, body, posted) VALUES (?, ?, ?, ?, ?)"
)
_SELECT_TURNS_SQL = (
    "SELECT session_id, ordinal, turn_identity, item_id, repository_id, repository, destination_number, app_id, "
    "completed_at, in_flight FROM github_conversation_turn ORDER BY completed_at, session_id, ordinal"
)
_SELECT_PARTS_SQL = (
    "SELECT part, body, posted FROM github_conversation_part WHERE session_id = ? AND ordinal = ? ORDER BY part"
)
_BEGIN_HANDOVER_SQL = "SELECT in_flight FROM github_conversation_turn WHERE session_id = ? AND ordinal = ?"
_SET_IN_FLIGHT_SQL = "UPDATE github_conversation_turn SET in_flight = ? WHERE session_id = ? AND ordinal = ?"
_MARK_POSTED_SQL = (
    "UPDATE github_conversation_part SET posted = 1 WHERE session_id = ? AND ordinal = ? AND part IN ("
    "SELECT part FROM github_conversation_part WHERE session_id = ? AND ordinal = ? AND posted = 0 "
    "ORDER BY part LIMIT ?)"
)
_COUNT_UNPOSTED_SQL = (
    "SELECT COUNT(*) FROM github_conversation_part WHERE session_id = ? AND ordinal = ? AND posted = 0"
)
_DELETE_TURN_SQL = "DELETE FROM github_conversation_turn WHERE session_id = ? AND ordinal = ?"
_DELETE_PARTS_SQL = "DELETE FROM github_conversation_part WHERE session_id = ? AND ordinal = ?"
_SELECT_START_SQL = "SELECT started_at FROM github_conversation_start WHERE singleton = 1"
_SAVE_START_SQL = "INSERT OR IGNORE INTO github_conversation_start(singleton, started_at) VALUES (1, ?)"
_SELECT_LEDGER_SQL = "SELECT ledger_issue_number FROM github_repository WHERE singleton = 1"
_TURN_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'github_conversation_turn'"
_BUSY_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class CapturedPart:
    """One protected comment of a captured turn and whether it is on GitHub."""

    part: int
    body: str
    posted: bool = False


@dataclass(frozen=True)
class SessionPointer:
    """How far a session's turns have been taken from the runtime: the last one captured or passed over."""

    last_identity: str
    last_ordinal: int


@dataclass(frozen=True)
class CapturedTurn:
    """One captured turn: where it goes, as which App, and its protected comments in order."""

    session_id: str
    ordinal: int
    turn_identity: str
    item_id: str
    repository_id: int
    repository: str
    destination_number: int
    app_id: int
    completed_at: datetime
    parts: tuple[CapturedPart, ...]
    in_flight: bool = False

    @property
    def unposted(self) -> tuple[CapturedPart, ...]:
        """The comments not yet on GitHub, in order."""
        return tuple(part for part in self.parts if not part.posted)


def initialize_conversation_bookkeeping(connection: sqlite3.Connection) -> None:
    """Install conversation bookkeeping beside the GitHub working-copy tables."""
    for statement in (_TURN_TABLE_DDL, _PART_TABLE_DDL, _POINTER_TABLE_DDL, _START_TABLE_DDL):
        connection.execute(statement)


class ConversationBookkeeping:
    """Read and write one working copy's conversation bookkeeping, each call in its own short transaction."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_SECONDS)
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def pointer(self, session_id: str) -> SessionPointer | None:
        """How far this session's turns have been taken; None for a session this working copy has not seen."""
        with self._connection() as connection:
            row = connection.execute(_SELECT_POINTER_SQL, (session_id,)).fetchone()
        return SessionPointer(last_identity=str(row[0]), last_ordinal=int(row[1])) if row is not None else None

    def advance_pointer(self, session_id: str, pointer: SessionPointer) -> None:
        """Move a session's pointer forward past a turn that needs no capture; it never moves back."""
        with self._connection() as connection:
            connection.execute(_SAVE_POINTER_SQL, (session_id, pointer.last_identity, pointer.last_ordinal))

    def capture(self, turn: CapturedTurn, captured_at: datetime) -> None:
        """Keep a protected turn and move its session's pointer past it, together; capturing twice keeps one."""
        with self._connection() as connection:
            connection.execute(
                _INSERT_TURN_SQL,
                (
                    turn.session_id,
                    turn.ordinal,
                    turn.turn_identity,
                    turn.item_id,
                    turn.repository_id,
                    turn.repository,
                    turn.destination_number,
                    turn.app_id,
                    turn.completed_at.isoformat(),
                    captured_at.isoformat(),
                    int(turn.in_flight),
                ),
            )
            for part in turn.parts:
                connection.execute(
                    _INSERT_PART_SQL, (turn.session_id, turn.ordinal, part.part, part.body, int(part.posted))
                )
            connection.execute(_SAVE_POINTER_SQL, (turn.session_id, turn.turn_identity, turn.ordinal))

    def pending_turns(self) -> list[CapturedTurn]:
        """Every captured turn with comments not yet on GitHub, in completion order.

        A working copy that predates the conversation tables holds none.
        """
        with self._connection() as connection:
            if connection.execute(_TURN_TABLE_EXISTS_SQL).fetchone() is None:
                return []
            turns: list[CapturedTurn] = []
            for row in connection.execute(_SELECT_TURNS_SQL).fetchall():
                completed_at = parse_iso_datetime(row[8])
                if completed_at is None:
                    continue
                parts = tuple(
                    CapturedPart(part=int(part[0]), body=str(part[1]), posted=bool(part[2]))
                    for part in connection.execute(_SELECT_PARTS_SQL, (row[0], row[1])).fetchall()
                )
                turns.append(
                    CapturedTurn(
                        session_id=str(row[0]),
                        ordinal=int(row[1]),
                        turn_identity=str(row[2]),
                        item_id=str(row[3]),
                        repository_id=int(row[4]),
                        repository=str(row[5]),
                        destination_number=int(row[6]),
                        app_id=int(row[7]),
                        completed_at=completed_at,
                        parts=parts,
                        in_flight=bool(row[9]),
                    )
                )
        return turns

    def begin_handover(self, session_id: str, ordinal: int) -> bool:
        """Mark a turn as handed to the master and say whether an earlier hand-over may have written some of it.

        The mark stays until the master's answer is received, so a hand-over that never learns its outcome, a lost
        reply or a restart, makes the next one read the destination first.
        """
        with self._connection() as connection:
            row = connection.execute(_BEGIN_HANDOVER_SQL, (session_id, ordinal)).fetchone()
            connection.execute(_SET_IN_FLIGHT_SQL, (1, session_id, ordinal))
        return bool(row[0]) if row is not None else False

    def end_handover(self, session_id: str, ordinal: int, written: int, *, uncertain: bool = False) -> bool:
        """Record the master's answer: its first ``written`` comments are on GitHub. True when the turn is complete.

        A turn whose last comment is on GitHub is forgotten. An answer that leaves the next comment's fate unknown
        keeps the turn marked as possibly sent, so its next hand-over reads the destination before writing.
        """
        with self._connection() as connection:
            connection.execute(_MARK_POSTED_SQL, (session_id, ordinal, session_id, ordinal, written))
            connection.execute(_SET_IN_FLIGHT_SQL, (int(uncertain), session_id, ordinal))
            remaining = connection.execute(_COUNT_UNPOSTED_SQL, (session_id, ordinal)).fetchone()
            if remaining is not None and int(remaining[0]) == 0:
                connection.execute(_DELETE_PARTS_SQL, (session_id, ordinal))
                connection.execute(_DELETE_TURN_SQL, (session_id, ordinal))
                return True
        return False

    def conversation_start(self) -> datetime | None:
        """The cached moment the project's conversation began, if it has been read."""
        with self._connection() as connection:
            row = connection.execute(_SELECT_START_SQL).fetchone()
        return parse_iso_datetime(row[0]) if row is not None else None

    def save_conversation_start(self, started_at: datetime) -> None:
        """Cache the moment the project's conversation began; the first one saved stays."""
        with self._connection() as connection:
            connection.execute(_SAVE_START_SQL, (started_at.isoformat(),))

    def ledger_issue_number(self) -> int | None:
        """The number of the project's ledger issue, if the store has opened one."""
        with self._connection() as connection:
            row = connection.execute(_SELECT_LEDGER_SQL).fetchone()
        return int(row[0]) if row is not None and row[0] is not None else None
