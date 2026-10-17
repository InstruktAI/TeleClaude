"""Move source ownership and source-derived diagnostics inside each mirror conversation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

_SOURCE_OBSERVATION_REVISION = 11
_PREVIOUS_SOURCE_OBSERVATION_REVISION = 10
_READ_DATA_REVISION_SQL = "PRAGMA user_version"
_WRITE_DATA_REVISION_SQL = f"PRAGMA user_version = {_SOURCE_OBSERVATION_REVISION}"
_MIGRATION_TRANSACTION_BEGIN_SQL = "BEGIN IMMEDIATE"
_SCHEMA_NOT_READY = "The mirror source-ownership migration requires derived-data revision 10."

_MIRRORS_TABLE_NAME = "mirrors"
_MIRROR_SOURCES_TABLE_NAME = "mirror_sources"
_UNREPROJECTABLE_SOURCES_TABLE_NAME = "mirror_unreprojectable_sources"
_SHRINK_REFUSALS_TABLE_NAME = "mirror_shrink_refusals"
_NATIVE_SESSION_ID_COLUMN = "native_session_id"
_MIRRORS_V11_TABLE = "mirrors_source_observation_v11"
_MIRROR_SOURCES_V11_TABLE = "mirror_sources_source_observation_v11"
_UNREPROJECTABLE_V11_TABLE = "mirror_unreprojectable_sources_source_observation_v11"
_SHRINK_REFUSALS_V11_TABLE = "mirror_shrink_refusals_source_observation_v11"

_MIRROR_COLUMNS = """\
id, native_session_id, source_identity, computer, agent, project_path, title,
timestamp_start, timestamp_end, conversation_text, message_count, metadata,
created_at, updated_at, summary, human_email, visibility, command, todo,
is_worker, derivation_version, session, position, covered_at, coverage_ready
"""

_MIRRORS_TABLE_TEMPLATE = """\
CREATE TABLE {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    native_session_id TEXT,
    source_identity TEXT,
    computer TEXT NOT NULL,
    agent TEXT NOT NULL,
    project_path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    timestamp_start TEXT,
    timestamp_end TEXT,
    conversation_text TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT DEFAULT '{{}}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT,
    human_email TEXT,
    visibility TEXT DEFAULT 'private',
    command TEXT,
    todo TEXT,
    is_worker INTEGER NOT NULL DEFAULT 0,
    derivation_version INTEGER NOT NULL DEFAULT 0,
    session INTEGER,
    position INTEGER,
    covered_at TEXT,
    coverage_ready INTEGER NOT NULL DEFAULT 0
)
"""

_MIRROR_SOURCES_TABLE_TEMPLATE = """\
CREATE TABLE IF NOT EXISTS {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mirror INTEGER NOT NULL,
    source_identity TEXT NOT NULL,
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
    updated_at TEXT NOT NULL,
    UNIQUE (mirror, source_identity)
)
"""

_MIRROR_MESSAGES_SQL = """\
CREATE TABLE IF NOT EXISTS mirror_messages (
    source INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    entry_index INTEGER NOT NULL,
    block_ordinal INTEGER NOT NULL,
    timestamp TEXT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (source, ordinal)
) WITHOUT ROWID
"""

_UNREPROJECTABLE_TABLE_TEMPLATE = """\
CREATE TABLE IF NOT EXISTS {table_name} (
    source INTEGER PRIMARY KEY,
    marked_at TEXT NOT NULL
)
"""

_SHRINK_REFUSALS_TABLE_TEMPLATE = """\
CREATE TABLE IF NOT EXISTS {table_name} (
    source INTEGER PRIMARY KEY,
    shrink_refused_at TEXT NOT NULL
)
"""

_INSERT_V11_MIRRORS_SQL = (
    f"INSERT INTO {_MIRRORS_V11_TABLE} ({_MIRROR_COLUMNS}) SELECT {_MIRROR_COLUMNS} FROM {_MIRRORS_TABLE_NAME}"
)
_INSERT_V11_MIRROR_SOURCES_SQL = f"INSERT INTO {_MIRROR_SOURCES_V11_TABLE} SELECT * FROM {_MIRROR_SOURCES_TABLE_NAME}"
_INSERT_V11_UNREPROJECTABLE_SQL = f"""\
INSERT INTO {_UNREPROJECTABLE_V11_TABLE} (source, marked_at)
SELECT {_MIRROR_SOURCES_TABLE_NAME}.id, {_UNREPROJECTABLE_SOURCES_TABLE_NAME}.marked_at
FROM {_UNREPROJECTABLE_SOURCES_TABLE_NAME}
JOIN {_MIRROR_SOURCES_TABLE_NAME}
ON {_MIRROR_SOURCES_TABLE_NAME}.source_identity = {_UNREPROJECTABLE_SOURCES_TABLE_NAME}.source_identity
"""
_INSERT_V11_SHRINK_REFUSALS_SQL = f"""\
INSERT INTO {_SHRINK_REFUSALS_V11_TABLE} (source, shrink_refused_at)
SELECT {_MIRROR_SOURCES_TABLE_NAME}.id, {_SHRINK_REFUSALS_TABLE_NAME}.shrink_refused_at
FROM {_SHRINK_REFUSALS_TABLE_NAME}
JOIN {_MIRROR_SOURCES_TABLE_NAME}
ON {_MIRROR_SOURCES_TABLE_NAME}.source_identity = {_SHRINK_REFUSALS_TABLE_NAME}.source_identity
"""
_DROP_TABLE_SQL_TEMPLATE = "DROP TABLE {table_name}"
_RENAME_TABLE_SQL_TEMPLATE = "ALTER TABLE {source_table} RENAME TO {target_table}"
_SOURCE_OBSERVATION_TABLES_TO_DROP = (
    _UNREPROJECTABLE_SOURCES_TABLE_NAME,
    _SHRINK_REFUSALS_TABLE_NAME,
    _MIRROR_SOURCES_TABLE_NAME,
    _MIRRORS_TABLE_NAME,
)
_SOURCE_OBSERVATION_TABLE_RENAMES = (
    (_UNREPROJECTABLE_V11_TABLE, _UNREPROJECTABLE_SOURCES_TABLE_NAME),
    (_SHRINK_REFUSALS_V11_TABLE, _SHRINK_REFUSALS_TABLE_NAME),
    (_MIRROR_SOURCES_V11_TABLE, _MIRROR_SOURCES_TABLE_NAME),
    (_MIRRORS_V11_TABLE, _MIRRORS_TABLE_NAME),
)

_MIRROR_AUXILIARY_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_source_identity ON mirrors(source_identity)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_project ON mirrors(project_path)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_session ON mirrors(session)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_is_worker ON mirrors(is_worker)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mirrors_session_unique ON mirrors(session) WHERE session IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_mirror_sources_mirror ON mirror_sources(mirror)",
    "CREATE INDEX IF NOT EXISTS idx_mirror_sources_native ON mirror_sources(native_session_id)",
)

_DROP_MIRROR_AUXILIARY_OBJECTS = (
    "DROP TRIGGER IF EXISTS mirrors_ai",
    "DROP TRIGGER IF EXISTS mirrors_ad",
    "DROP TRIGGER IF EXISTS mirrors_au",
    "DROP TRIGGER IF EXISTS mirrors_session_id_guard_insert",
    "DROP TRIGGER IF EXISTS mirrors_session_id_guard_update",
    "DROP TABLE IF EXISTS mirrors_fts",
)

_CREATE_MIRRORS_FTS_SQL = """\
CREATE VIRTUAL TABLE mirrors_fts USING fts5(
    title,
    conversation_text,
    content='mirrors',
    content_rowid='id'
)
"""
_REBUILD_MIRRORS_FTS_SQL = "INSERT INTO mirrors_fts(mirrors_fts) VALUES ('rebuild')"
_MIRRORS_FTS_TRIGGERS = (
    """\
    CREATE TRIGGER mirrors_ai AFTER INSERT ON mirrors BEGIN
        INSERT INTO mirrors_fts(rowid, title, conversation_text)
        VALUES (new.id, new.title, new.conversation_text);
    END
    """,
    """\
    CREATE TRIGGER mirrors_ad AFTER DELETE ON mirrors BEGIN
        INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
        VALUES ('delete', old.id, old.title, old.conversation_text);
    END
    """,
    """\
    CREATE TRIGGER mirrors_au AFTER UPDATE ON mirrors BEGIN
        INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
        VALUES ('delete', old.id, old.title, old.conversation_text);
        INSERT INTO mirrors_fts(rowid, title, conversation_text)
        VALUES (new.id, new.title, new.conversation_text);
    END
    """,
)


class _SessionIdGuardOperation(StrEnum):
    """The closed DML events that need the canonical session-id guard."""

    INSERT = "insert"
    UPDATE = "update"


_SESSION_ID_GUARD_EVENT_BY_OPERATION = {
    _SessionIdGuardOperation.INSERT: "INSERT",
    _SessionIdGuardOperation.UPDATE: "UPDATE OF {column}",
}
_SESSION_ID_GUARD_SQL_TEMPLATE = """\
CREATE TRIGGER IF NOT EXISTS mirrors_session_id_guard_{operation}
BEFORE {event} ON mirrors
WHEN NEW.{column} IS NOT NULL
 AND NOT (
    length(NEW.{column}) = 36
    AND NEW.{column} = lower(NEW.{column})
    AND substr(NEW.{column}, 9, 1) = '-'
    AND substr(NEW.{column}, 14, 1) = '-'
    AND substr(NEW.{column}, 19, 1) = '-'
    AND substr(NEW.{column}, 24, 1) = '-'
    AND replace(NEW.{column}, '-', '') NOT GLOB '*[^0-9a-f]*'
 )
BEGIN
    SELECT RAISE(ABORT, 'mirrors.{column} must be a canonical lowercase UUID');
END
"""


def create_current_source_observation_schema(conn: sqlite3.Connection) -> None:
    """Create fresh source/message and diagnostic tables with session-owned source keys."""
    conn.execute(_MIRROR_SOURCES_TABLE_TEMPLATE.format(table_name=_MIRROR_SOURCES_TABLE_NAME))
    conn.execute(_MIRROR_MESSAGES_SQL)
    conn.execute(_UNREPROJECTABLE_TABLE_TEMPLATE.format(table_name=_UNREPROJECTABLE_SOURCES_TABLE_NAME))
    conn.execute(_SHRINK_REFUSALS_TABLE_TEMPLATE.format(table_name=_SHRINK_REFUSALS_TABLE_NAME))
    conn.execute(_MIRROR_AUXILIARY_INDEXES[-2])
    conn.execute(_MIRROR_AUXILIARY_INDEXES[-1])


def create_session_id_guards(conn: sqlite3.Connection, column: str) -> None:
    """Restore the canonical UUID guard on the named native/session identity column."""
    for operation, event_template in _SESSION_ID_GUARD_EVENT_BY_OPERATION.items():
        conn.execute(
            _SESSION_ID_GUARD_SQL_TEMPLATE.format(
                operation=operation.value,
                event=event_template.format(column=column),
                column=column,
            )
        )


def migrate_source_observation_ownership(
    conn: sqlite3.Connection,
    store_path: str,
    snapshot_store: Callable[[sqlite3.Connection, str], Path],
) -> None:
    """Rebuild global source keys as per-mirror observations in one mandatory revision."""
    revision = int(conn.execute(_READ_DATA_REVISION_SQL).fetchone()[0])
    if revision >= _SOURCE_OBSERVATION_REVISION:
        return
    if revision != _PREVIOUS_SOURCE_OBSERVATION_REVISION:
        raise RuntimeError(_SCHEMA_NOT_READY)

    snapshot_store(conn, store_path)
    conn.execute(_MIGRATION_TRANSACTION_BEGIN_SQL)
    try:
        _migrate_tables(conn)
        conn.execute(_WRITE_DATA_REVISION_SQL)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_tables(conn: sqlite3.Connection) -> None:
    for statement in _DROP_MIRROR_AUXILIARY_OBJECTS:
        conn.execute(statement)

    conn.execute(_MIRRORS_TABLE_TEMPLATE.format(table_name=_MIRRORS_V11_TABLE))
    conn.execute(_INSERT_V11_MIRRORS_SQL)

    conn.execute(_MIRROR_SOURCES_TABLE_TEMPLATE.format(table_name=_MIRROR_SOURCES_V11_TABLE))
    conn.execute(_INSERT_V11_MIRROR_SOURCES_SQL)

    conn.execute(_UNREPROJECTABLE_TABLE_TEMPLATE.format(table_name=_UNREPROJECTABLE_V11_TABLE))
    conn.execute(_INSERT_V11_UNREPROJECTABLE_SQL)

    conn.execute(_SHRINK_REFUSALS_TABLE_TEMPLATE.format(table_name=_SHRINK_REFUSALS_V11_TABLE))
    conn.execute(_INSERT_V11_SHRINK_REFUSALS_SQL)

    for table_name in _SOURCE_OBSERVATION_TABLES_TO_DROP:
        conn.execute(_DROP_TABLE_SQL_TEMPLATE.format(table_name=table_name))
    for source_table, target_table in _SOURCE_OBSERVATION_TABLE_RENAMES:
        conn.execute(_RENAME_TABLE_SQL_TEMPLATE.format(source_table=source_table, target_table=target_table))

    for statement in _MIRROR_AUXILIARY_INDEXES:
        conn.execute(statement)
    create_session_id_guards(conn, _NATIVE_SESSION_ID_COLUMN)
    conn.execute(_CREATE_MIRRORS_FTS_SQL)
    for statement in _MIRRORS_FTS_TRIGGERS:
        conn.execute(statement)
    conn.execute(_REBUILD_MIRRORS_FTS_SQL)
