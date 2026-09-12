"""Idempotent schema and derived-data migrations for the mirrors store.

Every migration here runs on schema init and must be safe to re-run: they bring an
existing mirrors table up to the current shape and realign columns whose values are
derived rather than authored.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import ROLE_WORKER
from teleclaude.core.agents import AgentName
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.utils.transcript_discovery import (
    SessionId,
    classify_transcript,
    extract_project,
    extract_session_id,
)

logger = get_logger(__name__)

_ADD_COLUMN_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE mirrors ADD COLUMN summary TEXT",
    "ALTER TABLE mirrors ADD COLUMN human_email TEXT",
    "ALTER TABLE mirrors ADD COLUMN visibility TEXT DEFAULT 'private'",
    "ALTER TABLE mirrors ADD COLUMN command TEXT",
    "ALTER TABLE mirrors ADD COLUMN slug TEXT",
    "ALTER TABLE mirrors ADD COLUMN is_worker INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE mirrors ADD COLUMN derivation_version INTEGER NOT NULL DEFAULT 0",
)

_INDEX_STATEMENTS: tuple[str, ...] = (
    "DROP INDEX IF EXISTS idx_mirrors_is_agent_spawn",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email)",
    "CREATE INDEX IF NOT EXISTS idx_mirrors_is_worker ON mirrors(is_worker)",
)

_RENAME_AGENT_SPAWN_SQL = "ALTER TABLE mirrors RENAME COLUMN is_agent_spawn TO is_worker"

# SQLite reports an already-applied column migration through the message text alone,
# so these tokens are what distinguish "already migrated" from a real schema fault.
_DUPLICATE_COLUMN_ERROR = "duplicate column"
_MISSING_COLUMN_ERROR = "no such column"

# Bump when a rule below changes what a converged row should hold. Convergence is
# recorded in the database rather than re-derived per process: schema init runs on every
# process that opens the store, including read-only CLI calls, so an ungated scan would
# both re-read the table on every invocation and take a write lock a reader never needed.
_DATA_REVISION = 6

_READ_DATA_REVISION_SQL = "PRAGMA user_version"
_WRITE_DATA_REVISION_SQL = f"PRAGMA user_version = {_DATA_REVISION}"

_DATABASE_LOCKED_ERROR = "database is locked"
_SESSION_ID_REKEY_FAILED_EVENT = "mirror.session_id_rekey_failed"
_SESSION_ID_REKEY_COMPLETE_EVENT = "mirror.session_id_rekey_complete"
_PROJECT_RECONCILE_COMPLETE_EVENT = "mirror.project_reconcile_complete"
_RECORD_CONVERGENCE_COMPLETE_EVENT = "mirror.record_convergence_complete"
_TRANSCRIPT_PATH_FIELD = "transcript_path"

_CREATE_NULLABLE_MIRRORS_SQL = """\
CREATE TABLE mirrors_session_id_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    source_identity TEXT UNIQUE,
    computer TEXT NOT NULL,
    agent TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    timestamp_start TEXT,
    timestamp_end TEXT,
    conversation_text TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT,
    human_email TEXT,
    visibility TEXT DEFAULT 'private',
    command TEXT,
    slug TEXT,
    is_worker INTEGER NOT NULL DEFAULT 0,
    derivation_version INTEGER NOT NULL DEFAULT 0
)
"""

_COPY_MIRRORS_SQL = """\
INSERT INTO mirrors_session_id_v2 (
    id, session_id, source_identity, computer, agent, project, title,
    timestamp_start, timestamp_end, conversation_text, message_count,
    metadata, created_at, updated_at, summary, human_email, visibility,
    command, slug, is_worker, derivation_version
)
SELECT
    id, session_id, source_identity, computer, agent, project, title,
    timestamp_start, timestamp_end, conversation_text, message_count,
    metadata, created_at, updated_at, summary, human_email, visibility,
    command, slug, is_worker, derivation_version
FROM mirrors
"""

_RECREATE_MIRROR_AUXILIARY_SQL = """\
CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent);
CREATE INDEX IF NOT EXISTS idx_mirrors_project ON mirrors(project);
CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC);
CREATE INDEX IF NOT EXISTS idx_mirrors_source_identity ON mirrors(source_identity);
CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email);
CREATE INDEX IF NOT EXISTS idx_mirrors_is_worker ON mirrors(is_worker);
CREATE VIRTUAL TABLE mirrors_fts USING fts5(
    title,
    conversation_text,
    content='mirrors',
    content_rowid='id'
);
INSERT INTO mirrors_fts(mirrors_fts) VALUES ('rebuild');
CREATE TRIGGER mirrors_ai AFTER INSERT ON mirrors BEGIN
    INSERT INTO mirrors_fts(rowid, title, conversation_text)
    VALUES (new.id, new.title, new.conversation_text);
END;
CREATE TRIGGER mirrors_ad AFTER DELETE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
END;
CREATE TRIGGER mirrors_au AFTER UPDATE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
    INSERT INTO mirrors_fts(rowid, title, conversation_text)
    VALUES (new.id, new.title, new.conversation_text);
END;
"""

_DROP_MIRROR_AUXILIARY_SQL = """\
DROP TRIGGER IF EXISTS mirrors_ai;
DROP TRIGGER IF EXISTS mirrors_ad;
DROP TRIGGER IF EXISTS mirrors_au;
DROP TABLE IF EXISTS mirrors_fts;
"""

_SELECT_SESSION_ID_ROWS_SQL = "SELECT id, session_id, agent, metadata FROM mirrors"
_UPDATE_SESSION_ID_SQL = "UPDATE mirrors SET session_id = ? WHERE id = ?"
_SELECT_PROJECT_ROWS_SQL = "SELECT id, session_id, agent, project, metadata FROM mirrors"
_UPDATE_PROJECT_SQL = "UPDATE mirrors SET project = ? WHERE id = ?"
_SELECT_SESSION_PROJECTS_SQL = """\
SELECT native_session_id, native_log_file, project_path
FROM sessions
WHERE project_path IS NOT NULL AND project_path <> ''
ORDER BY created_at DESC
"""
_SELECT_CONVERGENCE_ROWS_SQL = "SELECT id, session_id, source_identity, agent, metadata FROM mirrors"
_DELETE_MIRROR_ROW_SQL = "DELETE FROM mirrors WHERE id = ?"
_DELETE_TOMBSTONE_BY_SOURCE_SQL = "DELETE FROM mirror_tombstones WHERE source_identity = ?"
_DELETE_UNREPROJECTABLE_BY_SOURCE_SQL = "DELETE FROM mirror_unreprojectable_sources WHERE source_identity = ?"
_DELETE_SHRINK_REFUSAL_BY_SOURCE_SQL = "DELETE FROM mirror_shrink_refusals WHERE source_identity = ?"
_SELECT_SESSION_ROLES_SQL = """\
SELECT native_log_file, system_role
FROM sessions
WHERE native_log_file IS NOT NULL AND native_log_file <> ''
ORDER BY created_at DESC
"""
_SELECT_SURVIVING_WORKER_ROWS_SQL = "SELECT id, is_worker, metadata FROM mirrors"
_UPDATE_IS_WORKER_SQL = "UPDATE mirrors SET is_worker = ? WHERE id = ?"
_MIRRORS_TABLE_INFO_SQL = "PRAGMA table_info(mirrors)"
_SESSION_ID_COLUMN = "session_id"
_DROP_MIRRORS_SQL = "DROP TABLE mirrors"
_RENAME_MIRRORS_SQL = "ALTER TABLE mirrors_session_id_v2 RENAME TO mirrors"

_CREATE_UNREPROJECTABLE_SOURCES_SQL = """\
CREATE TABLE IF NOT EXISTS mirror_unreprojectable_sources (
    source_identity TEXT PRIMARY KEY,
    marked_at TEXT NOT NULL
)
"""

_CREATE_SESSION_ID_GUARDS_SQL = """\
CREATE TRIGGER IF NOT EXISTS mirrors_session_id_guard_insert
BEFORE INSERT ON mirrors
WHEN NEW.session_id IS NOT NULL
 AND NOT (
    length(NEW.session_id) = 36
    AND NEW.session_id = lower(NEW.session_id)
    AND substr(NEW.session_id, 9, 1) = '-'
    AND substr(NEW.session_id, 14, 1) = '-'
    AND substr(NEW.session_id, 19, 1) = '-'
    AND substr(NEW.session_id, 24, 1) = '-'
    AND replace(NEW.session_id, '-', '') NOT GLOB '*[^0-9a-f]*'
 )
BEGIN
    SELECT RAISE(ABORT, 'mirrors.session_id must be a canonical lowercase UUID');
END;
CREATE TRIGGER IF NOT EXISTS mirrors_session_id_guard_update
BEFORE UPDATE OF session_id ON mirrors
WHEN NEW.session_id IS NOT NULL
 AND NOT (
    length(NEW.session_id) = 36
    AND NEW.session_id = lower(NEW.session_id)
    AND substr(NEW.session_id, 9, 1) = '-'
    AND substr(NEW.session_id, 14, 1) = '-'
    AND substr(NEW.session_id, 19, 1) = '-'
    AND substr(NEW.session_id, 24, 1) = '-'
    AND replace(NEW.session_id, '-', '') NOT GLOB '*[^0-9a-f]*'
 )
BEGIN
    SELECT RAISE(ABORT, 'mirrors.session_id must be a canonical lowercase UUID');
END;
"""


def migrate_add_mirror_columns(conn: sqlite3.Connection) -> None:
    """Idempotently bring mirrors schema and derived fields to the current contract."""
    _rename_agent_spawn_column(conn)
    for stmt in _ADD_COLUMN_STATEMENTS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if _DUPLICATE_COLUMN_ERROR not in str(exc).lower():
                raise
    for index_stmt in _INDEX_STATEMENTS:
        conn.execute(index_stmt)
    conn.execute(_CREATE_UNREPROJECTABLE_SOURCES_SQL)
    _converge_derived_data(conn)


def _converge_derived_data(conn: sqlite3.Connection) -> None:
    """Realign derived columns once per store, not once per process.

    Skips entirely when the store already records this revision, so the common path is
    one pragma read. A locked database means another process holds the write lock — the
    daemon reconciling, most often — and that process converges the same rows, so the
    revision is left unset and the work is simply retried on a later open. A reader must
    never fail because convergence could not run.
    """
    if int(conn.execute(_READ_DATA_REVISION_SQL).fetchone()[0]) >= _DATA_REVISION:
        return
    try:
        migrate_nullable_session_id(conn)
        reconcile_mirror_records(conn)
        reconcile_transcript_session_ids(conn)
        reconcile_mirror_projects(conn)
        conn.executescript(_CREATE_SESSION_ID_GUARDS_SQL)
        conn.execute(_WRITE_DATA_REVISION_SQL)
    except sqlite3.OperationalError as exc:
        if _DATABASE_LOCKED_ERROR not in str(exc).lower():
            raise


def migrate_nullable_session_id(conn: sqlite3.Connection) -> None:
    """Allow mirrors for transcripts that do not belong to an addressable session."""
    columns = conn.execute(_MIRRORS_TABLE_INFO_SQL).fetchall()
    session_column = next((column for column in columns if column[1] == _SESSION_ID_COLUMN), None)
    if session_column is None or not bool(session_column[3]):
        return
    conn.executescript(_DROP_MIRROR_AUXILIARY_SQL)
    conn.execute(_CREATE_NULLABLE_MIRRORS_SQL)
    conn.execute(_COPY_MIRRORS_SQL)
    conn.execute(_DROP_MIRRORS_SQL)
    conn.execute(_RENAME_MIRRORS_SQL)
    conn.executescript(_RECREATE_MIRROR_AUXILIARY_SQL)


def _session_role_map() -> dict[str, str]:
    """Load system_role attribution keyed by transcript path."""
    main_db_uri = f"file:{MAIN_DB_PATH.resolve()}?mode=ro"
    with sqlite3.connect(main_db_uri, uri=True) as main_conn:
        rows = main_conn.execute(_SELECT_SESSION_ROLES_SQL).fetchall()
    by_transcript_path: dict[str, str] = {}
    for native_log_file, system_role in rows:
        if native_log_file and system_role:
            by_transcript_path.setdefault(str(native_log_file), str(system_role))
    return by_transcript_path


def reconcile_mirror_records(conn: sqlite3.Connection) -> None:
    """Delete mirrors discovery no longer produces; realign `is_worker` from the record.

    A subagent transcript, a headless one-shot invocation, or a null-session row is
    exactly what discovery now refuses to recognize, so the archive must not keep
    holding it (UC-MSB-3, UC-MRL-13). `is_worker` is realigned from the joined record's
    `system_role` for every surviving row whose transcript path resolves to one; every
    other stored column — title, command, slug — is left as written, by decision. The
    file-existence and admission scan runs to completion before any write, so it never
    holds the write lock.
    """
    rows = conn.execute(_SELECT_CONVERGENCE_ROWS_SQL).fetchall()
    to_delete: list[tuple[int, str | None]] = []
    deleted_null_session = 0
    deleted_subagent = 0
    deleted_headless = 0
    for row_id, session_id, source_identity, raw_agent, raw_metadata in rows:
        if session_id is None:
            to_delete.append((row_id, source_identity))
            deleted_null_session += 1
            continue
        try:
            metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
            transcript_path = metadata.get(_TRANSCRIPT_PATH_FIELD) if isinstance(metadata, dict) else None
            if not isinstance(transcript_path, str) or not transcript_path:
                raise ValueError(_TRANSCRIPT_PATH_FIELD)
            agent = AgentName(raw_agent)
        except (OSError, TypeError, ValueError):
            continue
        path = Path(transcript_path).expanduser()
        if not path.exists():
            continue
        is_subagent, is_headless = classify_transcript(path, agent)
        if is_subagent:
            to_delete.append((row_id, source_identity))
            deleted_subagent += 1
        elif is_headless:
            to_delete.append((row_id, source_identity))
            deleted_headless += 1

    if to_delete:
        conn.executemany(_DELETE_MIRROR_ROW_SQL, [(row_id,) for row_id, _ in to_delete])
        source_identities = [(source_identity,) for _, source_identity in to_delete if source_identity]
        if source_identities:
            conn.executemany(_DELETE_TOMBSTONE_BY_SOURCE_SQL, source_identities)
            conn.executemany(_DELETE_UNREPROJECTABLE_BY_SOURCE_SQL, source_identities)
            conn.executemany(_DELETE_SHRINK_REFUSAL_BY_SOURCE_SQL, source_identities)

    role_by_path = _session_role_map()
    surviving = conn.execute(_SELECT_SURVIVING_WORKER_ROWS_SQL).fetchall()
    worker_updates: list[tuple[int, int]] = []
    for row_id, current_is_worker, raw_metadata in surviving:
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
        transcript_path = metadata.get(_TRANSCRIPT_PATH_FIELD) if isinstance(metadata, dict) else None
        if not isinstance(transcript_path, str) or not transcript_path:
            continue
        system_role = role_by_path.get(transcript_path)
        if system_role is None:
            continue
        target_is_worker = 1 if system_role == ROLE_WORKER else 0
        if int(current_is_worker) != target_is_worker:
            worker_updates.append((target_is_worker, row_id))
    if worker_updates:
        conn.executemany(_UPDATE_IS_WORKER_SQL, worker_updates)

    logger.info(
        _RECORD_CONVERGENCE_COMPLETE_EVENT,
        data_revision=_DATA_REVISION,
        total=len(rows),
        deleted_subagent=deleted_subagent,
        deleted_headless=deleted_headless,
        deleted_null_session=deleted_null_session,
        realigned=len(worker_updates),
    )


def reconcile_transcript_session_ids(conn: sqlite3.Connection) -> None:
    """Re-key non-UUID mirror rows from the identity carried by their transcript."""
    rows = conn.execute(_SELECT_SESSION_ID_ROWS_SQL).fetchall()
    updates: list[tuple[str, int]] = []
    codex_count = 0
    gemini_count = 0
    failed_count = 0
    for row_id, current_session_id, raw_agent, raw_metadata in rows:
        if current_session_id is None:
            continue
        try:
            SessionId(current_session_id)
        except ValueError:
            pass
        else:
            continue
        try:
            metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
            transcript_path = metadata.get(_TRANSCRIPT_PATH_FIELD) if isinstance(metadata, dict) else None
            if not isinstance(transcript_path, str) or not transcript_path:
                raise ValueError(_TRANSCRIPT_PATH_FIELD)
            agent = AgentName(raw_agent)
            session_id = extract_session_id(Path(transcript_path), agent)
        except (OSError, TypeError, ValueError) as exc:
            logger.error(
                _SESSION_ID_REKEY_FAILED_EVENT,
                mirror_id=row_id,
                agent=raw_agent,
                error=str(exc),
            )
            failed_count += 1
            continue
        updates.append((session_id, row_id))
        if agent is AgentName.CODEX:
            codex_count += 1
        elif agent is AgentName.GEMINI:
            gemini_count += 1
    if updates:
        conn.executemany(_UPDATE_SESSION_ID_SQL, updates)
    logger.info(
        _SESSION_ID_REKEY_COMPLETE_EVENT,
        data_revision=_DATA_REVISION,
        repaired=len(updates),
        unresolved=failed_count,
        failed=failed_count,
        total=len(rows),
        rekeyed_codex=codex_count,
        rekeyed_gemini=gemini_count,
    )


def _session_project_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Load project attribution keyed by native id and transcript path."""
    main_db_uri = f"file:{MAIN_DB_PATH.resolve()}?mode=ro"
    with sqlite3.connect(main_db_uri, uri=True) as main_conn:
        rows = main_conn.execute(_SELECT_SESSION_PROJECTS_SQL).fetchall()
    by_native_id: dict[str, str] = {}
    by_transcript_path: dict[str, str] = {}
    for native_session_id, native_log_file, project_path in rows:
        project = str(project_path)
        if native_session_id:
            by_native_id.setdefault(str(native_session_id), project)
        if native_log_file:
            by_transcript_path.setdefault(str(native_log_file), project)
    return by_native_id, by_transcript_path


def reconcile_mirror_projects(conn: sqlite3.Connection) -> None:
    """Replace historical path-tail labels with session or transcript project truth."""
    by_native_id, by_transcript_path = _session_project_maps()
    rows = conn.execute(_SELECT_PROJECT_ROWS_SQL).fetchall()
    updates: list[tuple[str, int]] = []
    session_count = 0
    transcript_count = 0
    cleared_unresolved = 0
    for row_id, session_id, raw_agent, current_project, raw_metadata in rows:
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
        transcript_path = metadata.get(_TRANSCRIPT_PATH_FIELD) if isinstance(metadata, dict) else None
        resolved_project = by_transcript_path.get(str(transcript_path)) if transcript_path else None
        if resolved_project is None and session_id:
            resolved_project = by_native_id.get(str(session_id))
        if resolved_project is not None:
            session_count += 1
        elif isinstance(transcript_path, str) and transcript_path:
            try:
                resolved_project = extract_project(Path(transcript_path), AgentName(raw_agent))
            except (OSError, TypeError, ValueError):
                resolved_project = None
            if resolved_project:
                transcript_count += 1
        if resolved_project is None and current_project and not Path(str(current_project)).is_absolute():
            resolved_project = ""
            cleared_unresolved += 1
        if resolved_project is not None and resolved_project != current_project:
            updates.append((resolved_project, row_id))
    if updates:
        conn.executemany(_UPDATE_PROJECT_SQL, updates)
    logger.info(
        _PROJECT_RECONCILE_COMPLETE_EVENT,
        total=len(rows),
        updated=len(updates),
        resolved_from_session=session_count,
        resolved_from_transcript=transcript_count,
        cleared_unresolved=cleared_unresolved,
    )


def _rename_agent_spawn_column(conn: sqlite3.Connection) -> None:
    """Rename the legacy `is_agent_spawn` column to `is_worker`.

    The column always held one question — is this session a dispatched worker — but its
    original name asserted a wider one, that any agent-spawned session belonged in it.
    That conflation is what hid orchestrators from search, so the name is corrected
    rather than left to reintroduce the same reading.

    Raises on anything but the column already being absent, which is the normal state
    for a fresh database and for one already migrated.
    """
    try:
        conn.execute(_RENAME_AGENT_SPAWN_SQL)
    except sqlite3.OperationalError as exc:
        if _MISSING_COLUMN_ERROR not in str(exc).lower():
            raise
