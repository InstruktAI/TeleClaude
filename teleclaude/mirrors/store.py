"""Storage and query helpers for conversation mirrors."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import quote

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from teleclaude import paths as tc_paths
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_utc_datetime, parse_iso_datetime
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.identity_reach import Reach
from teleclaude.mirrors._attribution import (
    MirrorSessionAttribution,
    backfill_session_attributions,
    upsert_session_attribution,
)
from teleclaude.mirrors._migrations import (
    LATEST_DATA_REVISION,
    create_current_attribution_schema,
    migrate_add_mirror_columns,
)
from teleclaude.mirrors._types import JsonValue

# Search shows only the sessions worth auditing; dispatched workers are the noise.
_WORKER_EXCLUSION_CLAUSE = "mirrors.is_worker = 0"
_WORKER_ONLY_CLAUSE = "mirrors.is_worker = 1"
_NATIVE_SESSION_ID_FIELD = "native_session_id"
_FTS_MATCH_CLAUSE = "mirrors_fts MATCH :match_query"
_IDENTITY_FILTER_CLAUSE = "(mirrors.human_email = :identity OR mirrors.source_identity = :identity)"
_PROJECT_FILTER_CLAUSE = "mirrors.project_path = :project"
_FTS_SEARCH_FROM = "FROM mirrors_fts JOIN mirrors ON mirrors_fts.rowid = mirrors.id"
_SELECTOR_SEARCH_FROM = "FROM mirrors"
_FTS_RESULT_JOIN = "JOIN mirrors_fts ON mirrors_fts.rowid = mirrors.id"
_FTS_RESULT_MATCH_CLAUSE = "AND mirrors_fts MATCH :match_query"
_FTS_SNIPPET_SELECT = "snippet(mirrors_fts, 1, '', '', '…', 12) AS snippet"
_SELECTOR_SNIPPET_SELECT = "'' AS snippet"
_UNREPROJECTABLE_MATCH_CLAUSE = (
    "NOT EXISTS (SELECT 1 FROM mirror_unreprojectable_sources "
    "WHERE mirror_unreprojectable_sources.source_identity = mirrors.source_identity)"
)
_UNREPROJECTABLE_SOURCE_CLAUSE = (
    "EXISTS (SELECT 1 FROM mirror_unreprojectable_sources "
    "WHERE mirror_unreprojectable_sources.source_identity = mirrors.source_identity)"
)
_MIRROR_SHRINK_REFUSALS_TABLE = "mirror_shrink_refusals"
_SHRINK_REFUSED_AT_FIELD = "shrink_refused_at"
_IDENTITY_PARAM = "identity"
_PROJECT_PARAM = "project"
_CALLER_EMAIL_PARAM = "caller_email"
_SOURCE_IDENTITY_PARAM = "source_identity"
_METADATA_PARAM = "metadata"
_SCOPE_SESSION_ALIAS = "scope_session"
_SQL_PARAMETER_SEPARATOR = ", "
_SQL_OR_SEPARATOR = " OR "
_SCOPE_SESSION_SUBJECT_COLUMN = "scope_session.subject"
_SCOPE_SESSION_OWNER_COLUMN = "scope_session.subject_owner"
_SCOPE_SESSION_PRINCIPAL_COLUMN = "scope_session.principal"
_PERSON_MIRROR_SESSION_SCOPE_CLAUSE_TEMPLATE = (
    "EXISTS (SELECT 1 FROM mirror_sessions AS {alias} WHERE {alias}.id = mirrors.session AND ({reach_clause}))"
)
# Email identifies ownership only when the mirror has no session attribution.
_UNATTRIBUTED_PERSON_EMAIL_SCOPE_CLAUSE = "mirrors.session IS NULL AND mirrors.human_email = :caller_email"
_PERSON_MIRROR_ACCESS_CLAUSE_TEMPLATE = "({session_scope_clause} OR ({unattributed_email_clause}))"
_SQL_AND_SEPARATOR = " AND "
_BEGIN_IMMEDIATE_SQL = "BEGIN IMMEDIATE"
_SELECT_EXISTING_MIRROR_METADATA_SQL = "SELECT metadata FROM mirrors WHERE source_identity = :source_identity"
_SELECT_MIRROR_TOMBSTONES_SQL = (
    "SELECT source_identity, agent, transcript_path, file_size, file_mtime, created_at FROM mirror_tombstones"
)
_SEARCH_SQL_TEMPLATE = """
    WITH ranked_candidates AS (
        SELECT
            COALESCE(mirrors.timestamp_start, mirrors.updated_at) AS sort_timestamp,
            mirrors.updated_at AS ranking_updated_at,
            mirrors.id AS physical_id,
            ROW_NUMBER() OVER (PARTITION BY mirrors.agent, CASE WHEN mirrors.session IS NULL THEN mirrors.id ELSE mirrors.session END ORDER BY COALESCE(mirrors.timestamp_start, mirrors.updated_at) DESC, mirrors.updated_at DESC, mirrors.id DESC) AS canonical_rank
        {search_from}
        WHERE {where_clause}
    )
    SELECT
        mirrors.native_session_id,
        mirror_sessions.session_id,
        mirrors.computer,
        mirrors.agent,
        mirrors.project_path,
        mirrors.title,
        ranked_candidates.sort_timestamp,
        {snippet_select},
        mirrors.conversation_text,
        mirrors.metadata,
        mirrors.human_email,
        mirrors.visibility,
        mirrors.source_identity
    FROM ranked_candidates
    JOIN mirrors ON mirrors.id = ranked_candidates.physical_id
    LEFT JOIN mirror_sessions ON mirror_sessions.id = mirrors.session
    {result_join}
    WHERE canonical_rank = 1 {result_match_clause}
    ORDER BY ranked_candidates.sort_timestamp DESC, ranked_candidates.ranking_updated_at DESC, ranked_candidates.physical_id DESC
    LIMIT :limit
"""
_SEARCH_COUNT_SQL_TEMPLATE = "SELECT COUNT(*) {search_from} WHERE {where_clause}"
_CANONICAL_COUNT_SQL_TEMPLATE = """
    SELECT COUNT(*) FROM (
        SELECT 1 {search_from}
        WHERE {where_clause}
        GROUP BY mirrors.agent, CASE WHEN mirrors.session IS NULL THEN mirrors.id ELSE mirrors.session END
    )
"""
_GET_MIRROR_SQL_TEMPLATE = f"""
    SELECT mirrors.native_session_id, mirror_sessions.session_id, mirrors.session, mirrors.position,
        mirrors.source_identity, mirrors.computer, mirrors.agent, mirrors.project_path,
        mirrors.title, mirrors.timestamp_start, mirrors.timestamp_end, mirrors.conversation_text,
        mirrors.message_count, mirrors.metadata, mirrors.created_at, mirrors.updated_at, mirrors.summary,
        mirrors.human_email, mirrors.visibility, mirrors.command, mirrors.todo, mirrors.is_worker,
        mirrors.derivation_version,
        mirror_shrink_refusals.{_SHRINK_REFUSED_AT_FIELD}
    FROM mirrors
    LEFT JOIN mirror_sessions ON mirror_sessions.id = mirrors.session
    LEFT JOIN {_MIRROR_SHRINK_REFUSALS_TABLE} AS mirror_shrink_refusals
        ON mirror_shrink_refusals.source_identity = mirrors.source_identity
    WHERE {{where_clause}} ORDER BY mirrors.updated_at DESC LIMIT 1
"""
_RECORD_MIRROR_SHRINK_REFUSAL_SQL = f"""
    INSERT INTO {_MIRROR_SHRINK_REFUSALS_TABLE} (source_identity, {_SHRINK_REFUSED_AT_FIELD})
    VALUES (:source_identity, :{_SHRINK_REFUSED_AT_FIELD})
    ON CONFLICT(source_identity) DO UPDATE SET {_SHRINK_REFUSED_AT_FIELD} = excluded.{_SHRINK_REFUSED_AT_FIELD}
"""
_CLEAR_MIRROR_SHRINK_REFUSAL_SQL = (
    f"DELETE FROM {_MIRROR_SHRINK_REFUSALS_TABLE} WHERE source_identity = :source_identity"
)

_schema_initialized: set[str] = set()
_rw_engines: dict[str, Engine] = {}
_ro_engines: dict[str, Engine] = {}


@dataclass(frozen=True)
class MirrorSearchResult:
    """A single FTS5 search hit from the mirrors table."""

    native_session_id: str | None
    session_id: str | None
    computer: str
    agent: str
    project_path: str
    title: str
    sort_timestamp: str
    timestamp: str
    topic: str
    conversation_text: str
    metadata: dict[str, JsonValue]
    human_email: str | None = None
    visibility: str = "private"
    source_identity: str | None = None


@dataclass(frozen=True)
class MirrorSearchPage:
    """Search hits plus worker matches withheld by the default filter."""

    results: list[MirrorSearchResult]
    excluded_workers: int
    physical_candidate_count: int
    eligible_candidate_count: int
    canonical_count: int
    unreprojectable_excluded_count: int


class MirrorCoverageState(StrEnum):
    """Reader-visible state of a retained mirror's current-source coverage."""

    RETAINED_AFTER_SHRINK = "retained_after_shrink"
    NO_RECORDED_SHRINK = "no_recorded_shrink"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MirrorRecord:
    """Full mirror row for a session transcript."""

    native_session_id: str | None
    session_id: str | None
    position: int | None
    computer: str | None
    agent: str
    project_path: str | None
    title: str | None
    timestamp_start: str | None
    timestamp_end: str | None
    conversation_text: str
    message_count: int
    metadata: dict[str, JsonValue]
    created_at: str
    updated_at: str
    source_identity: str | None = None
    summary: str | None = None
    human_email: str | None = None
    visibility: str | None = None
    command: str | None = None
    todo: str | None = None
    is_worker: bool | None = None
    derivation_version: int = 0
    coverage_state: MirrorCoverageState = MirrorCoverageState.UNKNOWN
    shrink_refused_at: str | None = None


@dataclass(frozen=True)
class MirrorTombstoneRecord:
    """Tombstone record for empty/deleted transcripts."""

    source_identity: str
    agent: str
    transcript_path: str
    file_size: int
    file_mtime: str
    created_at: str


def _ensure_schema(conn: sqlite3.Connection, path: str) -> None:
    """Create mirrors tables and FTS index if they don't exist."""
    if path in _schema_initialized:
        return
    mirrors_exists = conn.execute(_MIRRORS_TABLE_EXISTS_SQL).fetchone() is not None
    conn.executescript(_MIRRORS_SCHEMA)
    if mirrors_exists:
        migrate_add_mirror_columns(conn, path, backfill_session_attributions)
    else:
        create_current_attribution_schema(conn)
        conn.execute(f"PRAGMA user_version = {LATEST_DATA_REVISION}")
    _schema_initialized.add(path)


_MIRRORS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    native_session_id TEXT, source_identity TEXT UNIQUE, computer TEXT NOT NULL, agent TEXT NOT NULL,
    project_path TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', timestamp_start TEXT, timestamp_end TEXT,
    conversation_text TEXT NOT NULL DEFAULT '', message_count INTEGER NOT NULL DEFAULT 0, metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, summary TEXT, human_email TEXT,
    visibility TEXT DEFAULT 'private', command TEXT, todo TEXT, is_worker INTEGER NOT NULL DEFAULT 0,
    derivation_version INTEGER NOT NULL DEFAULT 0, session INTEGER, position INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent);
CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC);
CREATE INDEX IF NOT EXISTS idx_mirrors_source_identity ON mirrors(source_identity);
CREATE TABLE IF NOT EXISTS mirror_tombstones (source_identity TEXT PRIMARY KEY, agent TEXT NOT NULL DEFAULT '',
    transcript_path TEXT NOT NULL DEFAULT '', file_size INTEGER NOT NULL DEFAULT 0, file_mtime TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS mirror_unreprojectable_sources (source_identity TEXT PRIMARY KEY, marked_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mirror_shrink_refusals (source_identity TEXT PRIMARY KEY, shrink_refused_at TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS mirrors_fts USING fts5(title, conversation_text, content='mirrors', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS mirrors_ai AFTER INSERT ON mirrors BEGIN
    INSERT INTO mirrors_fts(rowid, title, conversation_text) VALUES (new.id, new.title, new.conversation_text);
END;
CREATE TRIGGER IF NOT EXISTS mirrors_ad AFTER DELETE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text) VALUES ('delete', old.id, old.title, old.conversation_text);
END;
CREATE TRIGGER IF NOT EXISTS mirrors_au AFTER UPDATE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text) VALUES ('delete', old.id, old.title, old.conversation_text);
    INSERT INTO mirrors_fts(rowid, title, conversation_text) VALUES (new.id, new.title, new.conversation_text);
END;
"""

_MIRRORS_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mirrors'"
_UPSERT_MIRROR_SQL = """\
INSERT INTO mirrors (
    native_session_id, source_identity, computer, agent, project_path, title, timestamp_start,
    timestamp_end, conversation_text, message_count, metadata, created_at, updated_at,
    human_email, visibility, command, todo, is_worker, derivation_version, session, position
) VALUES (
    :native_session_id, :source_identity, COALESCE(:computer, ''), :agent,
    COALESCE(:project_path, ''), COALESCE(:title, ''), :timestamp_start, :timestamp_end,
    :conversation_text, :message_count, :metadata, :created_at, :updated_at,
    :human_email, COALESCE(:visibility, 'private'), :command, :todo,
    COALESCE(:is_worker, 0), :derivation_version, :session, :position
)
ON CONFLICT(source_identity) DO UPDATE SET
    native_session_id = excluded.native_session_id,
    session = COALESCE(excluded.session, mirrors.session),
    position = COALESCE(excluded.position, mirrors.position),
    computer = COALESCE(NULLIF(excluded.computer, ''), mirrors.computer),
    agent = excluded.agent,
    project_path = COALESCE(NULLIF(excluded.project_path, ''), mirrors.project_path),
    title = COALESCE(NULLIF(excluded.title, ''), mirrors.title),
    timestamp_start = excluded.timestamp_start,
    timestamp_end = excluded.timestamp_end,
    conversation_text = excluded.conversation_text,
    message_count = excluded.message_count,
    metadata = excluded.metadata,
    updated_at = excluded.updated_at,
    human_email = COALESCE(NULLIF(excluded.human_email, ''), mirrors.human_email),
    visibility = COALESCE(NULLIF(excluded.visibility, ''), mirrors.visibility),
    command = COALESCE(NULLIF(excluded.command, ''), mirrors.command),
    todo = COALESCE(NULLIF(excluded.todo, ''), mirrors.todo),
    is_worker = COALESCE(excluded.is_worker, mirrors.is_worker),
    derivation_version = excluded.derivation_version
"""
_RECORD_SESSION_CLOSE_SQL = """\
UPDATE mirror_sessions SET closed_at = COALESCE(closed_at, :closed_at), updated_at = :updated_at
WHERE session_id = :session_id AND closed_at IS NULL
"""
_OPEN_ATTRIBUTED_SESSION_IDS_SQL = "SELECT session_id FROM mirror_sessions WHERE closed_at IS NULL"
_DELETE_MIRROR_BY_NATIVE_SESSION_ID_SQL = "DELETE FROM mirrors WHERE native_session_id = :native_session_id"


def _resolve_mirrors_db_path(db: str | Path | None = None) -> str:
    """Resolve a mirrors database path and ensure the parent directory exists."""
    resolved = Path(db).expanduser().resolve() if db is not None else tc_paths.MIRRORS_DB_PATH.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def _read_only_sqlite_uri(path: str) -> str:
    """Build a read-only SQLite URI for SQLAlchemy."""
    return f"file:{quote(path)}?mode=ro&uri=true"


def _get_rw_engine(db: str | Path | None = None) -> Engine:
    """Return the cached writable mirrors engine, initializing schema on first use."""
    path = _resolve_mirrors_db_path(db)
    engine = _rw_engines.get(path)
    if engine is None:
        engine = create_sync_db_engine(path)
        _rw_engines[path] = engine
    if path not in _schema_initialized:
        with engine.raw_connection() as raw_conn:
            conn = cast(sqlite3.Connection, raw_conn)
            _ensure_schema(conn, path)
            conn.commit()
    return engine


def _get_ro_engine(db: str | Path | None = None) -> Engine:
    """Return the cached read-only mirrors engine, bootstrapping schema via the RW engine."""
    path = _resolve_mirrors_db_path(db)
    if path not in _schema_initialized:
        _get_rw_engine(path)
    target = _read_only_sqlite_uri(path)
    engine = _ro_engines.get(target)
    if engine is None:
        engine = create_sync_db_engine(target)
        _ro_engines[target] = engine
    return engine


def _agent_values(agents: Sequence[AgentName | str]) -> list[str]:
    return [agent.value if isinstance(agent, AgentName) else str(agent) for agent in agents]


def _match_query(query: str) -> str:
    terms = [term for term in query.strip().split() if term]
    escaped = [f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms]
    return " AND ".join(escaped)


def _format_search_timestamp(value: str | None) -> str:
    if not value:
        return ""
    parsed = parse_iso_datetime(value)
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return format_utc_datetime(parsed)


def _topic_for_row(row: RowMapping) -> str:
    snippet = row["snippet"]
    if isinstance(snippet, str) and snippet.strip():
        return snippet
    title = row["title"]
    if isinstance(title, str) and title.strip():
        return title
    conversation = row["conversation_text"]
    if isinstance(conversation, str):
        return conversation[:70]
    return ""


def _is_missing_table_error(exc: SqlAlchemyOperationalError | sqlite3.OperationalError) -> bool:
    """Return whether an exception indicates an absent SQLite table."""
    cause = exc.orig if isinstance(exc, SqlAlchemyOperationalError) else exc
    return "no such table" in str(cause).lower()


def _parse_metadata(value: object) -> dict[str, JsonValue]:
    """Parse a metadata JSON blob into the public typed shape."""
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        return {}
    return cast(dict[str, JsonValue], parsed)


def _optional_str(value: object) -> str | None:
    """Return a string value or None when the database value is null/empty."""
    if value in (None, ""):
        return None
    return str(value)


def _int_value(value: object) -> int:
    """Return an integer value from a row mapping cell."""
    if isinstance(value, int):
        return value
    if value in (None, ""):
        return 0
    return int(str(value))


def _optional_bool(value: object) -> bool | None:
    """Return a boolean fact when the write supplied one."""
    return None if value is None else bool(_int_value(value))


def _optional_int(value: object) -> int | None:
    """Return an integer when a row contains a value."""
    return None if value is None else _int_value(value)


def _mirror_search_result_from_row(row: RowMapping) -> MirrorSearchResult:
    """Convert a SQLAlchemy row mapping into the public search dataclass."""
    sort_timestamp = str(row.get("sort_timestamp") or "")
    return MirrorSearchResult(
        native_session_id=_optional_str(row.get(_NATIVE_SESSION_ID_FIELD)),
        session_id=_optional_str(row.get("session_id")),
        computer=str(row["computer"]),
        agent=str(row["agent"]),
        project_path=str(row["project_path"]),
        title=str(row["title"] or ""),
        sort_timestamp=sort_timestamp,
        timestamp=_format_search_timestamp(sort_timestamp),
        topic=_topic_for_row(row),
        conversation_text=str(row["conversation_text"] or ""),
        metadata=_parse_metadata(row.get("metadata")),
        human_email=_optional_str(row.get("human_email")),
        visibility=str(row.get("visibility") or "private"),
        source_identity=_optional_str(row.get("source_identity")),
    )


def _mirror_record_from_row(row: RowMapping) -> MirrorRecord:
    """Convert a SQLAlchemy row mapping into the public mirror dataclass."""
    return MirrorRecord(
        native_session_id=_optional_str(row.get(_NATIVE_SESSION_ID_FIELD)),
        session_id=_optional_str(row.get("session_id")),
        position=_optional_int(row.get("position")),
        computer=_optional_str(row.get("computer")),
        agent=str(row["agent"]),
        project_path=_optional_str(row.get("project_path")),
        title=_optional_str(row.get("title")),
        timestamp_start=_optional_str(row.get("timestamp_start")),
        timestamp_end=_optional_str(row.get("timestamp_end")),
        conversation_text=str(row.get("conversation_text") or ""),
        message_count=_int_value(row.get("message_count")),
        metadata=_parse_metadata(row.get("metadata")),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        source_identity=_optional_str(row.get("source_identity")),
        summary=_optional_str(row.get("summary")),
        human_email=_optional_str(row.get("human_email")),
        visibility=_optional_str(row.get("visibility")),
        command=_optional_str(row.get("command")),
        todo=_optional_str(row.get("todo")),
        is_worker=_optional_bool(row.get("is_worker")),
        derivation_version=_int_value(row.get("derivation_version")),
        coverage_state=(
            MirrorCoverageState.RETAINED_AFTER_SHRINK
            if row.get(_SHRINK_REFUSED_AT_FIELD) is not None
            else MirrorCoverageState.NO_RECORDED_SHRINK
        ),
        shrink_refused_at=_optional_str(row.get(_SHRINK_REFUSED_AT_FIELD)),
    )


def _tombstone_from_row(row: RowMapping) -> MirrorTombstoneRecord:
    """Convert a SQLAlchemy row mapping into the public tombstone dataclass."""
    return MirrorTombstoneRecord(
        source_identity=str(row["source_identity"]),
        agent=str(row["agent"]),
        transcript_path=str(row["transcript_path"]),
        file_size=_int_value(row["file_size"]),
        file_mtime=str(row["file_mtime"]),
        created_at=str(row["created_at"]),
    )


def search_mirrors(
    query: str,
    agents: Sequence[AgentName | str],
    *,
    reach: Reach,
    limit: int = 20,
    db: str | Path | None = None,
    computers: Sequence[str] | None = None,
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
) -> MirrorSearchPage:
    """Search the local mirrors FTS table.

    Dispatched-worker mirrors are excluded unless ``include_workers`` is set.
    """
    match_query = _match_query(query)
    if not match_query and not identity and not project:
        return MirrorSearchPage(
            results=[],
            excluded_workers=0,
            physical_candidate_count=0,
            eligible_candidate_count=0,
            canonical_count=0,
            unreprojectable_excluded_count=0,
        )

    candidate_clauses = [_FTS_MATCH_CLAUSE] if match_query else []
    params: dict[str, object] = {  # guard: loose-dict - SQL bind params are assembled dynamically.
        "limit": limit,
        "match_query": match_query,
    }
    agent_values = _agent_values(agents)
    if agent_values:
        placeholders: list[str] = []
        for index, agent in enumerate(agent_values):
            key = f"agent_{index}"
            placeholders.append(f":{key}")
            params[key] = agent
        candidate_clauses.append(f"mirrors.agent IN ({', '.join(placeholders)})")
    if computers:
        placeholders = []
        for index, computer in enumerate(computers):
            key = f"computer_{index}"
            placeholders.append(f":{key}")
            params[key] = computer
        candidate_clauses.append(f"mirrors.computer IN ({', '.join(placeholders)})")
    if identity:
        candidate_clauses.append(_IDENTITY_FILTER_CLAUSE)
        params[_IDENTITY_PARAM] = identity
    if project:
        candidate_clauses.append(_PROJECT_FILTER_CLAUSE)
        params[_PROJECT_PARAM] = project
    _apply_access_filter(candidate_clauses, params, reach)
    eligible_clauses = [*candidate_clauses]
    if match_query:
        eligible_clauses.append(_UNREPROJECTABLE_MATCH_CLAUSE)
    if not include_workers:
        eligible_clauses.append(_WORKER_EXCLUSION_CLAUSE)

    worker_count_clauses = [*candidate_clauses, _WORKER_ONLY_CLAUSE]
    unreprojectable_count_clauses = [*candidate_clauses]
    if match_query:
        unreprojectable_count_clauses.append(_UNREPROJECTABLE_SOURCE_CLAUSE)
        if not include_workers:
            unreprojectable_count_clauses.append(_WORKER_EXCLUSION_CLAUSE)

    sql = _SEARCH_SQL_TEMPLATE.format(
        snippet_select=_FTS_SNIPPET_SELECT if match_query else _SELECTOR_SNIPPET_SELECT,
        search_from=_FTS_SEARCH_FROM if match_query else _SELECTOR_SEARCH_FROM,
        where_clause=_SQL_AND_SEPARATOR.join(eligible_clauses),
        result_join=_FTS_RESULT_JOIN if match_query else "",
        result_match_clause=_FTS_RESULT_MATCH_CLAUSE if match_query else "",
    )
    candidate_count_sql = _SEARCH_COUNT_SQL_TEMPLATE.format(
        search_from=_FTS_SEARCH_FROM if match_query else _SELECTOR_SEARCH_FROM,
        where_clause=_SQL_AND_SEPARATOR.join(candidate_clauses),
    )
    eligible_count_sql = _SEARCH_COUNT_SQL_TEMPLATE.format(
        search_from=_FTS_SEARCH_FROM if match_query else _SELECTOR_SEARCH_FROM,
        where_clause=_SQL_AND_SEPARATOR.join(eligible_clauses),
    )
    canonical_count_sql = _CANONICAL_COUNT_SQL_TEMPLATE.format(
        search_from=_FTS_SEARCH_FROM if match_query else _SELECTOR_SEARCH_FROM,
        where_clause=_SQL_AND_SEPARATOR.join(eligible_clauses),
    )
    worker_count_sql = _SEARCH_COUNT_SQL_TEMPLATE.format(
        search_from=_FTS_SEARCH_FROM if match_query else _SELECTOR_SEARCH_FROM,
        where_clause=_SQL_AND_SEPARATOR.join(worker_count_clauses),
    )
    unreprojectable_count_sql = _SEARCH_COUNT_SQL_TEMPLATE.format(
        search_from=_FTS_SEARCH_FROM if match_query else _SELECTOR_SEARCH_FROM,
        where_clause=_SQL_AND_SEPARATOR.join(unreprojectable_count_clauses),
    )

    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            physical_candidate_count = int(conn.execute(text(candidate_count_sql), params).scalar_one())
            eligible_candidate_count = int(conn.execute(text(eligible_count_sql), params).scalar_one())
            canonical_count = int(conn.execute(text(canonical_count_sql), params).scalar_one())
            excluded_workers = 0 if include_workers else int(conn.execute(text(worker_count_sql), params).scalar_one())
            unreprojectable_excluded_count = (
                int(conn.execute(text(unreprojectable_count_sql), params).scalar_one()) if match_query else 0
            )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return MirrorSearchPage(
                results=[],
                excluded_workers=0,
                physical_candidate_count=0,
                eligible_candidate_count=0,
                canonical_count=0,
                unreprojectable_excluded_count=0,
            )
        raise

    return MirrorSearchPage(
        results=[_mirror_search_result_from_row(row) for row in rows],
        excluded_workers=excluded_workers,
        physical_candidate_count=physical_candidate_count,
        eligible_candidate_count=eligible_candidate_count,
        canonical_count=canonical_count,
        unreprojectable_excluded_count=unreprojectable_excluded_count,
    )


def get_mirror(
    native_session_id: str | None = None,
    *,
    reach: Reach,
    db: str | Path | None = None,
    computer: str | None = None,
    source_identity: str | None = None,
) -> MirrorRecord | None:
    """Fetch a mirror by native transcript id or source identity."""
    clauses: list[str]
    params: dict[str, object]  # guard: loose-dict - SQL bind params vary by lookup path.
    if source_identity:
        clauses = ["mirrors.source_identity = :source_identity"]
        params = {"source_identity": source_identity}
    elif native_session_id:
        clauses = ["mirrors.native_session_id = :native_session_id"]
        params = {"native_session_id": native_session_id}
        if computer:
            clauses.append("mirrors.computer = :computer")
            params["computer"] = computer
    else:
        return None

    _apply_access_filter(clauses, params, reach)

    sql = _GET_MIRROR_SQL_TEMPLATE.format(where_clause=_SQL_AND_SEPARATOR.join(clauses))

    try:
        with _get_ro_engine(db).connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise

    if row is None:
        return None

    return _mirror_record_from_row(row)


def get_session_mirror(
    session_id: str,
    *,
    reach: Reach,
    db: str | Path | None = None,
) -> MirrorRecord | None:
    """Fetch the latest transcript mirror attributed to one TeleClaude session."""
    clauses = ["mirror_sessions.session_id = :session_id"]
    params: dict[str, object] = {"session_id": session_id}  # guard: loose-dict - access scope extends these SQL values.
    _apply_access_filter(clauses, params, reach)
    sql = _GET_MIRROR_SQL_TEMPLATE.format(where_clause=_SQL_AND_SEPARATOR.join(clauses))
    sql = sql.replace("ORDER BY mirrors.updated_at DESC", "ORDER BY mirrors.position DESC, mirrors.updated_at DESC")
    try:
        with _get_ro_engine(db).connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise
    return _mirror_record_from_row(row) if row is not None else None


def upsert_mirror(
    record: MirrorRecord,
    attribution: MirrorSessionAttribution | None,
    *,
    db: str | Path | None = None,
) -> None:
    """Upsert the mirror and its session attribution atomically."""
    if not record.source_identity:
        msg = "MirrorRecord.source_identity is required"
        raise ValueError(msg)

    metadata_json = json.dumps(record.metadata, sort_keys=True)
    now = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {  # guard: loose-dict - SQL columns accept heterogeneous bound values.
        "agent": record.agent,
        "command": record.command,
        "computer": record.computer,
        "conversation_text": record.conversation_text,
        "created_at": record.created_at,
        "derivation_version": record.derivation_version,
        "human_email": record.human_email,
        "is_worker": None if record.is_worker is None else int(record.is_worker),
        "message_count": record.message_count,
        _METADATA_PARAM: metadata_json,
        "project_path": record.project_path,
        "native_session_id": record.native_session_id,
        "position": record.position,
        "session": None,
        "todo": record.todo,
        "source_identity": record.source_identity,
        "timestamp_end": record.timestamp_end,
        "timestamp_start": record.timestamp_start,
        "title": record.title,
        "updated_at": record.updated_at,
        "visibility": record.visibility,
    }
    with _get_rw_engine(db).connect() as conn:
        conn.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)  # guard: raw-sql - serialize metadata merge with mirror writes.
        try:
            raw_conn = cast(sqlite3.Connection, conn.connection.driver_connection)
            if attribution is not None:
                payload["session"] = upsert_session_attribution(raw_conn, attribution, now)
            stored_metadata = _parse_metadata(
                conn.execute(
                    text(_SELECT_EXISTING_MIRROR_METADATA_SQL),
                    {_SOURCE_IDENTITY_PARAM: record.source_identity},
                ).scalar_one_or_none()
            )
            metadata = dict(stored_metadata)
            metadata.update(
                {
                    key: value
                    for key, value in record.metadata.items()
                    if value is not None or key not in stored_metadata
                }
            )
            payload[_METADATA_PARAM] = json.dumps(metadata, sort_keys=True)
            conn.execute(text(_UPSERT_MIRROR_SQL), payload)
            conn.execute(
                text("DELETE FROM mirror_unreprojectable_sources WHERE source_identity = :source_identity"),
                {_SOURCE_IDENTITY_PARAM: record.source_identity},
            )
            conn.execute(text(_CLEAR_MIRROR_SHRINK_REFUSAL_SQL), {_SOURCE_IDENTITY_PARAM: record.source_identity})
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def open_attributed_session_ids(*, db: str | Path | None = None) -> list[str]:
    """Return TeleClaude session ids whose close has not yet been recorded."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(_OPEN_ATTRIBUTED_SESSION_IDS_SQL)).scalars().all()
            return [str(session_id) for session_id in rows]
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return []
        raise


def record_session_close(
    session_id: str,
    closed_at: str,
    *,
    db: str | Path | None = None,
) -> bool:
    """Record a session close once without touching any transcript mirror."""
    updated_at = datetime.now(UTC).isoformat()
    with _get_rw_engine(db).begin() as conn:
        result = conn.execute(
            text(_RECORD_SESSION_CLOSE_SQL),
            {"session_id": session_id, "closed_at": closed_at, "updated_at": updated_at},
        )
        return result.rowcount > 0


def record_mirror_shrink_refusal(
    source_identity: str,
    *,
    shrink_refused_at: str,
    db: str | Path | None = None,
) -> None:
    """Record the latest preserved-mirror observation after a smaller projection."""
    with _get_rw_engine(db).begin() as conn:
        conn.execute(
            text(_RECORD_MIRROR_SHRINK_REFUSAL_SQL),
            {"source_identity": source_identity, _SHRINK_REFUSED_AT_FIELD: shrink_refused_at},
        )


def delete_mirror(
    native_session_id: str | None = None,
    *,
    db: str | Path | None = None,
    source_identity: str | None = None,
) -> None:
    """Delete a mirror row if it exists."""
    if not native_session_id and not source_identity:
        return
    with _get_rw_engine(db).begin() as conn:
        if source_identity:
            conn.execute(
                text("DELETE FROM mirrors WHERE source_identity = :source_identity"),
                {"source_identity": source_identity},
            )
        else:
            conn.execute(
                text(_DELETE_MIRROR_BY_NATIVE_SESSION_ID_SQL),
                {"native_session_id": native_session_id},
            )


def _apply_access_filter(
    clauses: list[str],
    params: dict[str, object],  # guard: loose-dict - SQL bind params are mutated by caller filters.
    reach: Reach,
) -> None:
    """Apply the already-resolved mirror access scope to a query."""
    if reach.everything:
        return
    reach_clause, reach_parameters = reach.sql_predicate(
        subject_col=_SCOPE_SESSION_SUBJECT_COLUMN,
        owner_col=_SCOPE_SESSION_OWNER_COLUMN,
        principal_col=_SCOPE_SESSION_PRINCIPAL_COLUMN,
    )
    params.update(reach_parameters)
    session_scope_clause = _PERSON_MIRROR_SESSION_SCOPE_CLAUSE_TEMPLATE.format(
        alias=_SCOPE_SESSION_ALIAS,
        reach_clause=reach_clause,
    )
    if reach.email is not None:
        clauses.append(
            _PERSON_MIRROR_ACCESS_CLAUSE_TEMPLATE.format(
                session_scope_clause=session_scope_clause,
                unattributed_email_clause=_UNATTRIBUTED_PERSON_EMAIL_SCOPE_CLAUSE,
            )
        )
        params[_CALLER_EMAIL_PARAM] = reach.email
    else:
        clauses.append(session_scope_clause)


@dataclass(frozen=True)
class OrphanMirror:
    """A stale stored mirror whose source transcript may no longer be available."""

    source_identity: str
    agent: str
    transcript_path: str | None


def mark_mirror_unreprojectable(
    source_identity: str,
    *,
    marked_at: str,
    db: str | Path | None = None,
) -> None:
    """Record that a stale source cannot be truthfully regenerated without its transcript."""
    with _get_rw_engine(db).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mirror_unreprojectable_sources (source_identity, marked_at) "
                "VALUES (:source_identity, :marked_at) "
                "ON CONFLICT(source_identity) DO NOTHING"
            ),
            {"marked_at": marked_at, "source_identity": source_identity},
        )


def get_mirror_tombstones(db: str | Path | None = None) -> dict[str, MirrorTombstoneRecord]:
    """Read a source-identity keyed snapshot of existing tombstones."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(_SELECT_MIRROR_TOMBSTONES_SQL)).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return {}
        raise
    records = (_tombstone_from_row(row) for row in rows)
    return {record.source_identity: record for record in records}


def upsert_mirror_tombstone(record: MirrorTombstoneRecord, *, db: str | Path | None = None) -> None:
    """Insert or update an empty-transcript tombstone."""
    with _get_rw_engine(db).begin() as conn:
        conn.execute(
            text(
                """
            INSERT INTO mirror_tombstones (
                source_identity,
                agent,
                transcript_path,
                file_size,
                file_mtime,
                created_at
            )
            VALUES (
                :source_identity,
                :agent,
                :transcript_path,
                :file_size,
                :file_mtime,
                :created_at
            )
            ON CONFLICT(source_identity) DO UPDATE SET
                agent = excluded.agent,
                transcript_path = excluded.transcript_path,
                file_size = excluded.file_size,
                file_mtime = excluded.file_mtime,
                created_at = excluded.created_at
            """
            ),
            {
                "agent": record.agent,
                "created_at": record.created_at,
                "file_mtime": record.file_mtime,
                "file_size": record.file_size,
                "source_identity": record.source_identity,
                "transcript_path": record.transcript_path,
            },
        )


def delete_mirror_tombstone(source_identity: str, *, db: str | Path | None = None) -> None:
    """Delete a tombstone if it exists."""
    with _get_rw_engine(db).begin() as conn:
        conn.execute(
            text("DELETE FROM mirror_tombstones WHERE source_identity = :source_identity"),
            {"source_identity": source_identity},
        )
