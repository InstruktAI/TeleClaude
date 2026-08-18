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

from teleclaude.constants import WORKER_COMMANDS
from teleclaude.core.agents import AgentName
from teleclaude.mirrors.derivation import is_known_launch_command, render_title
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.utils.transcript_discovery import SessionId, extract_project, extract_session_id

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

_SELECT_COMMAND_ROWS_SQL = "SELECT id, command, slug, title FROM mirrors WHERE command IS NOT NULL AND command <> ''"

_UPDATE_TITLE_SQL = "UPDATE mirrors SET title = ? WHERE id = ?"

_CLEAR_WORKER_SQL_TEMPLATE = (
    "UPDATE mirrors SET is_worker = 0 WHERE is_worker = 1 AND (command IS NULL OR command NOT IN ({placeholders}))"
)

_SET_WORKER_SQL_TEMPLATE = "UPDATE mirrors SET is_worker = 1 WHERE is_worker = 0 AND command IN ({placeholders})"

# SQLite reports an already-applied column migration through the message text alone,
# so these tokens are what distinguish "already migrated" from a real schema fault.
_DUPLICATE_COLUMN_ERROR = "duplicate column"
_MISSING_COLUMN_ERROR = "no such column"

_PLACEHOLDER = "?"
_PLACEHOLDER_SEPARATOR = ", "

# Bump when a rule below changes what a converged row should hold. Convergence is
# recorded in the database rather than re-derived per process: schema init runs on every
# process that opens the store, including read-only CLI calls, so an ungated scan would
# both re-read the table on every invocation and take a write lock a reader never needed.
_DATA_REVISION = 4

_READ_DATA_REVISION_SQL = "PRAGMA user_version"
_WRITE_DATA_REVISION_SQL = f"PRAGMA user_version = {_DATA_REVISION}"

_DATABASE_LOCKED_ERROR = "database is locked"
_SESSION_ID_REKEY_FAILED_EVENT = "mirror.session_id_rekey_failed"
_SESSION_ID_REKEY_COMPLETE_EVENT = "mirror.session_id_rekey_complete"
_PROJECT_RECONCILE_COMPLETE_EVENT = "mirror.project_reconcile_complete"
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
        reconcile_transcript_session_ids(conn)
        reconcile_mirror_projects(conn)
        reconcile_worker_classification(conn)
        reconcile_derived_titles(conn)
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


def reconcile_transcript_session_ids(conn: sqlite3.Connection) -> None:
    """Re-key non-UUID mirror rows from the identity carried by their transcript."""
    rows = conn.execute(_SELECT_SESSION_ID_ROWS_SQL).fetchall()
    updates: list[tuple[str | None, int]] = []
    codex_count = 0
    gemini_count = 0
    subagent_count = 0
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
        if session_id is None:
            subagent_count += 1
        elif agent is AgentName.CODEX:
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
        cleared_subagent=subagent_count,
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


def reconcile_worker_classification(conn: sqlite3.Connection) -> None:
    """Realign stored `is_worker` with the current worker-command set.

    The flag is derived from the row's launch command, never authored, so a row whose
    stored value disagrees with today's rule is stale rather than intentional. Rows are
    reclassified in place from the persisted `command`, which costs one narrow update
    and leaves `conversation_text` untouched — a `DERIVATION_VERSION` bump would instead
    push every transcript back through full generation, summarizer call included, to
    settle a question the stored column already answers.

    Idempotent: once aligned the predicate matches nothing, so later calls do no work.
    """
    placeholders = _PLACEHOLDER_SEPARATOR.join(_PLACEHOLDER * len(WORKER_COMMANDS))
    workers = sorted(WORKER_COMMANDS)
    conn.execute(_CLEAR_WORKER_SQL_TEMPLATE.format(placeholders=placeholders), workers)
    conn.execute(_SET_WORKER_SQL_TEMPLATE.format(placeholders=placeholders), workers)


def reconcile_derived_titles(conn: sqlite3.Connection) -> None:
    """Realign stored titles with the command each row records having been launched by.

    A row carrying a launch command owes that command's rendered title, so a stored row
    still holding text from an older derivation — a leaked doc heading, the raw command
    line — is stale and is rebuilt from the persisted `command` and `slug`.

    Only a command that names a real deployed artifact is trusted. Detection also fires
    on path fragments and prose, and those rows hold a genuine first-message title that
    rendering would replace with a humanized fragment; leaving them is the conservative
    side of an irreversible overwrite.

    Idempotent: a row already carrying its rendered title yields no update.
    """
    rows = conn.execute(_SELECT_COMMAND_ROWS_SQL).fetchall()
    updates: list[tuple[str, int]] = []
    for row_id, command, slug, title in rows:
        if not is_known_launch_command(command):
            continue
        rendered = render_title(command, slug)
        if rendered and rendered != title:
            updates.append((rendered, row_id))
    if updates:
        conn.executemany(_UPDATE_TITLE_SQL, updates)
