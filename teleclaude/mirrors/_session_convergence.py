"""Session-owned conversation shape of the mirror store, and the convergence that brings older stores to it.

A conversation mirror is one row per TeleClaude session. Each native transcript that holds part of
the conversation is a source row beneath it, keyed by its source identity; a source keeps its
conversational messages, or, when the store predates structured messages and the transcript is gone,
the rendered text it held as one archival segment.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_DUPLICATE_COLUMN_ERROR = "duplicate column"
_TRANSCRIPT_PATH_FIELD = "transcript_path"
_CONVERGED_EVENT = "mirror.session_owned_convergence_complete"

_ADD_COVERED_AT_SQL = "ALTER TABLE mirrors ADD COLUMN covered_at TEXT"
_ADD_COVERAGE_READY_SQL = "ALTER TABLE mirrors ADD COLUMN coverage_ready INTEGER NOT NULL DEFAULT 0"

_SESSION_OWNED_TABLES_SQL = """\
CREATE TABLE IF NOT EXISTS mirror_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mirror INTEGER NOT NULL,
    source_identity TEXT NOT NULL UNIQUE,
    native_session_id TEXT,
    agent TEXT NOT NULL,
    transcript_path TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    file_size INTEGER,
    file_mtime_ns TEXT,
    missing_at TEXT,
    derivation_version INTEGER NOT NULL DEFAULT 0,
    archival_text TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    timestamp_start TEXT,
    timestamp_end TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mirror_sources_mirror ON mirror_sources(mirror);
CREATE INDEX IF NOT EXISTS idx_mirror_sources_native ON mirror_sources(native_session_id);
CREATE TABLE IF NOT EXISTS mirror_messages (
    source INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    entry_index INTEGER NOT NULL,
    block_ordinal INTEGER NOT NULL,
    timestamp TEXT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (source, ordinal)
) WITHOUT ROWID;
"""

_UNIQUE_SESSION_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mirrors_session_unique ON mirrors(session) WHERE session IS NOT NULL"
)

_SELECT_CONVERGING_ROWS_SQL = """\
SELECT id, native_session_id, source_identity, agent, session, position, timestamp_start, timestamp_end,
    conversation_text, message_count, derivation_version, metadata, created_at, updated_at, command, todo
FROM mirrors
WHERE id NOT IN (SELECT mirror FROM mirror_sources)
"""
_INSERT_SOURCE_SQL = """\
INSERT OR IGNORE INTO mirror_sources (
    mirror, source_identity, native_session_id, agent, transcript_path, position, derivation_version,
    archival_text, message_count, timestamp_start, timestamp_end, created_at, updated_at
) VALUES (
    :mirror, :source_identity, :native_session_id, :agent, :transcript_path, :position, :derivation_version,
    :archival_text, :message_count, :timestamp_start, :timestamp_end, :created_at, :updated_at
)
"""
_CONSOLIDATE_MIRROR_SQL = """\
UPDATE mirrors SET conversation_text = :conversation_text, message_count = :message_count,
    timestamp_start = :timestamp_start, timestamp_end = :timestamp_end,
    command = COALESCE(command, :command), todo = COALESCE(todo, :todo)
WHERE id = :id
"""
_DELETE_MIRROR_SQL = "DELETE FROM mirrors WHERE id = ?"
_ARCHIVAL_SEGMENT_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class _OldMirrorRow:
    """One pre-convergence mirror row: a single native transcript's conversation."""

    id: int
    native_session_id: str | None
    source_identity: str
    agent: str
    session: int | None
    position: int | None
    timestamp_start: str | None
    timestamp_end: str | None
    conversation_text: str
    message_count: int
    derivation_version: int
    transcript_path: str | None
    created_at: str
    updated_at: str
    command: str | None
    todo: str | None


def create_session_owned_schema(conn: sqlite3.Connection) -> None:
    """Create the source and message tables and the one-mirror-per-session guard on a store with no duplicates."""
    conn.executescript(_SESSION_OWNED_TABLES_SQL)
    conn.execute(_UNIQUE_SESSION_INDEX_SQL)


def _create_session_owned_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_SESSION_OWNED_TABLES_SQL)


def _add_coverage_columns(conn: sqlite3.Connection) -> None:
    for statement in (_ADD_COVERED_AT_SQL, _ADD_COVERAGE_READY_SQL):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if _DUPLICATE_COLUMN_ERROR not in str(exc).lower():
                raise


def _transcript_path(raw_metadata: object) -> str | None:
    if not isinstance(raw_metadata, str) or not raw_metadata:
        return None
    try:
        metadata = json.loads(raw_metadata)
    except json.JSONDecodeError:
        return None
    path = metadata.get(_TRANSCRIPT_PATH_FIELD) if isinstance(metadata, dict) else None
    return path if isinstance(path, str) and path else None


def _old_rows(conn: sqlite3.Connection) -> list[_OldMirrorRow]:
    rows = conn.execute(_SELECT_CONVERGING_ROWS_SQL).fetchall()  # guard: raw-sql - migration-owned mirror scan.
    return [
        _OldMirrorRow(
            id=int(row[0]),
            native_session_id=row[1],
            source_identity=str(row[2]),
            agent=str(row[3]),
            session=None if row[4] is None else int(row[4]),
            position=None if row[5] is None else int(row[5]),
            timestamp_start=row[6],
            timestamp_end=row[7],
            conversation_text=str(row[8] or ""),
            message_count=int(row[9] or 0),
            derivation_version=int(row[10] or 0),
            transcript_path=_transcript_path(row[11]),
            created_at=str(row[12]),
            updated_at=str(row[13]),
            command=row[14],
            todo=row[15],
        )
        for row in rows
        if row[2]
    ]


def _lineage_order(rows: list[_OldMirrorRow]) -> list[_OldMirrorRow]:
    """Order a conversation's old rows by recorded position, then start time, then identity."""
    return sorted(
        rows,
        key=lambda row: (
            row.position is None,
            row.position if row.position is not None else 0,
            row.timestamp_start or "",
            row.id,
        ),
    )


def _group_by_conversation(rows: list[_OldMirrorRow]) -> list[list[_OldMirrorRow]]:
    """Group old rows by TeleClaude attribution; a row with none is its own conversation."""
    attributed: dict[int, list[_OldMirrorRow]] = {}
    groups: list[list[_OldMirrorRow]] = []
    for row in rows:
        if row.session is None:
            groups.append([row])
        else:
            attributed.setdefault(row.session, []).append(row)
    groups.extend(attributed.values())
    return groups


def _latest_recorded(values: list[str | None]) -> str | None:
    """The launch fact the newest row that recorded it holds, so a surviving row that lacks it keeps what was known."""
    return next((value for value in reversed(values) if value), None)


def _consolidate(conn: sqlite3.Connection, ordered: list[_OldMirrorRow]) -> None:
    """Make the newest source's row the conversation and every old row a source beneath it."""
    target = ordered[-1]
    for index, row in enumerate(ordered):
        conn.execute(  # guard: raw-sql - migration-owned source row.
            _INSERT_SOURCE_SQL,
            {
                "mirror": target.id,
                "source_identity": row.source_identity,
                "native_session_id": row.native_session_id,
                "agent": row.agent,
                "transcript_path": row.transcript_path,
                "position": row.position if row.position is not None else index,
                "derivation_version": row.derivation_version,
                "archival_text": row.conversation_text,
                "message_count": row.message_count,
                "timestamp_start": row.timestamp_start,
                "timestamp_end": row.timestamp_end,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    if len(ordered) == 1:
        return
    texts = [row.conversation_text for row in ordered if row.conversation_text]
    starts = [row.timestamp_start for row in ordered if row.timestamp_start]
    ends = [row.timestamp_end for row in ordered if row.timestamp_end]
    conn.execute(  # guard: raw-sql - migration-owned consolidation of one conversation.
        _CONSOLIDATE_MIRROR_SQL,
        dict(
            id=target.id,
            conversation_text=_ARCHIVAL_SEGMENT_SEPARATOR.join(texts),
            message_count=sum(row.message_count for row in ordered),
            timestamp_start=starts[0] if starts else None,
            timestamp_end=ends[-1] if ends else None,
            command=_latest_recorded([row.command for row in ordered]),
            todo=_latest_recorded([row.todo for row in ordered]),
        ),
    )
    conn.executemany(_DELETE_MIRROR_SQL, [(row.id,) for row in ordered[:-1]])


def converge_session_owned_conversations(conn: sqlite3.Connection) -> None:
    """Consolidate every conversation's source mirrors into one mirror row with its sources beneath it.

    Rows sharing a session attribution become one conversation ordered by recorded position then start
    time; each old row is kept as a source whose stored rendered text is one archival segment, so no
    stored conversation is parsed into guessed messages. A row without attribution becomes a
    single-source mirror. Re-derivation from the transcripts that still exist is the reconciliation
    pass's work, never this step's.
    """
    _add_coverage_columns(conn)
    _create_session_owned_tables(conn)
    groups = _group_by_conversation(_old_rows(conn))
    for group in groups:
        _consolidate(conn, _lineage_order(group))
    conn.execute(_UNIQUE_SESSION_INDEX_SQL)
    logger.info(_CONVERGED_EVENT, conversations=len(groups), sources=sum(len(group) for group in groups))
