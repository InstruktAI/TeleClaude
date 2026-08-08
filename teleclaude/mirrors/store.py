"""Storage and query helpers for conversation mirrors."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from teleclaude import paths as tc_paths
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_local_datetime, parse_iso_datetime
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.mirrors._migrations import migrate_add_mirror_columns

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_schema_initialized: set[str] = set()
_rw_engines: dict[str, Engine] = {}
_ro_engines: dict[str, Engine] = {}
_main_ro_engines: dict[str, Engine] = {}


@dataclass(frozen=True)
class MirrorSearchResult:
    """A single FTS5 search hit from the mirrors table."""

    session_id: str
    computer: str
    agent: str
    project: str
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
class MirrorRecord:
    """Full mirror row for a session transcript."""

    session_id: str
    computer: str
    agent: str
    project: str
    title: str
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
    visibility: str = "private"
    command: str | None = None
    slug: str | None = None
    is_worker: bool = False
    derivation_version: int = 0


@dataclass(frozen=True)
class MirrorTombstoneRecord:
    """Tombstone record for empty/deleted transcripts."""

    source_identity: str
    agent: str
    transcript_path: str
    file_size: int
    file_mtime: str
    created_at: str


@dataclass(frozen=True)
class SessionMirrorContext:
    """Lightweight session context looked up for mirror reconciliation."""

    session_id: str
    computer: str
    agent: str | None
    project: str
    transcript_path: str | None
    human_email: str | None = None
    visibility: str | None = None
    last_input_origin: str | None = None
    adapter_metadata_json: str | None = None


def _ensure_schema(conn: sqlite3.Connection, path: str) -> None:
    """Create mirrors tables and FTS index if they don't exist."""
    if path in _schema_initialized:
        return
    conn.executescript(_MIRRORS_SCHEMA)
    migrate_add_mirror_columns(conn)
    _schema_initialized.add(path)


_MIRRORS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
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
);
CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent);
CREATE INDEX IF NOT EXISTS idx_mirrors_project ON mirrors(project);
CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC);
CREATE INDEX IF NOT EXISTS idx_mirrors_source_identity ON mirrors(source_identity);
CREATE TABLE IF NOT EXISTS mirror_tombstones (
    source_identity TEXT PRIMARY KEY,
    agent TEXT NOT NULL DEFAULT '',
    transcript_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    file_mtime TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS mirrors_fts USING fts5(
    title,
    conversation_text,
    content='mirrors',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS mirrors_ai AFTER INSERT ON mirrors BEGIN
    INSERT INTO mirrors_fts(rowid, title, conversation_text)
    VALUES (new.id, new.title, new.conversation_text);
END;
CREATE TRIGGER IF NOT EXISTS mirrors_ad AFTER DELETE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
END;
CREATE TRIGGER IF NOT EXISTS mirrors_au AFTER UPDATE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
    INSERT INTO mirrors_fts(rowid, title, conversation_text)
    VALUES (new.id, new.title, new.conversation_text);
END;
"""


def _connect_rw(db: str | Path | None = None) -> sqlite3.Connection:  # pyright: ignore[reportUnusedFunction]
    conn = cast(sqlite3.Connection, _get_rw_engine(db).raw_connection())
    conn.row_factory = sqlite3.Row
    return conn


def _connect_ro(db: str | Path | None = None) -> sqlite3.Connection:  # pyright: ignore[reportUnusedFunction]
    conn = cast(sqlite3.Connection, _get_ro_engine(db).raw_connection())
    conn.row_factory = sqlite3.Row
    return conn


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


def _get_main_ro_engine() -> Engine:
    """Return the cached read-only main teleclaude.db engine for session lookups."""
    target = _read_only_sqlite_uri(str(tc_paths.MAIN_DB_PATH.resolve()))
    engine = _main_ro_engines.get(target)
    if engine is None:
        engine = create_sync_db_engine(target)
        _main_ro_engines[target] = engine
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
    return format_local_datetime(parsed, include_date=True)


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


def _mirror_search_result_from_row(row: RowMapping) -> MirrorSearchResult:
    """Convert a SQLAlchemy row mapping into the public search dataclass."""
    sort_timestamp = str(row.get("sort_timestamp") or "")
    return MirrorSearchResult(
        session_id=str(row["session_id"]),
        computer=str(row["computer"]),
        agent=str(row["agent"]),
        project=str(row["project"]),
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
        session_id=str(row["session_id"]),
        computer=str(row["computer"]),
        agent=str(row["agent"]),
        project=str(row["project"]),
        title=str(row.get("title") or ""),
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
        visibility=str(row.get("visibility") or "private"),
        command=_optional_str(row.get("command")),
        slug=_optional_str(row.get("slug")),
        is_worker=bool(_int_value(row.get("is_worker"))),
        derivation_version=_int_value(row.get("derivation_version")),
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
    limit: int = 20,
    db: str | Path | None = None,
    computers: Sequence[str] | None = None,
    caller_email: str | None = None,
    caller_role: str | None = None,
) -> list[MirrorSearchResult]:
    """Search the local mirrors FTS table."""
    match_query = _match_query(query)
    if not match_query:
        return []

    clauses = ["mirrors_fts MATCH :match_query"]
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
        clauses.append(f"mirrors.agent IN ({', '.join(placeholders)})")
    if computers:
        placeholders = []
        for index, computer in enumerate(computers):
            key = f"computer_{index}"
            placeholders.append(f":{key}")
            params[key] = computer
        clauses.append(f"mirrors.computer IN ({', '.join(placeholders)})")
    clauses.append("mirrors.is_worker = 0")
    _apply_role_filter(clauses, params, caller_email, caller_role)

    sql = f"""
        SELECT
            mirrors.session_id,
            mirrors.computer,
            mirrors.agent,
            mirrors.project,
            mirrors.title,
            COALESCE(mirrors.timestamp_start, mirrors.updated_at) AS sort_timestamp,
            snippet(mirrors_fts, 1, '', '', '…', 12) AS snippet,
            mirrors.conversation_text,
            mirrors.metadata,
            mirrors.human_email,
            mirrors.visibility,
            mirrors.source_identity
        FROM mirrors_fts
        JOIN mirrors ON mirrors_fts.rowid = mirrors.id
        WHERE {" AND ".join(clauses)}
        ORDER BY COALESCE(mirrors.timestamp_start, mirrors.updated_at) DESC
        LIMIT :limit
    """

    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return []
        raise

    return [_mirror_search_result_from_row(row) for row in rows]


def get_mirror(
    session_id: str | None = None,
    *,
    db: str | Path | None = None,
    computer: str | None = None,
    source_identity: str | None = None,
    caller_email: str | None = None,
    caller_role: str | None = None,
) -> MirrorRecord | None:
    """Fetch a mirror by exact or prefix session id."""
    clauses: list[str]
    params: dict[str, object]  # guard: loose-dict - SQL bind params vary by lookup path.
    if source_identity:
        clauses = ["source_identity = :source_identity"]
        params = {
            "session_id_exact": None,
            "session_id_prefix": "",
            "source_identity": source_identity,
        }
    elif session_id:
        clauses = ["(session_id = :session_id_exact OR session_id LIKE :session_id_prefix)"]
        params = {
            "session_id_exact": session_id,
            "session_id_prefix": f"{session_id}%",
        }
        if computer:
            clauses.append("computer = :computer")
            params["computer"] = computer
    else:
        return None

    _apply_role_filter(clauses, params, caller_email, caller_role)

    sql = f"""
        SELECT
            session_id,
            source_identity,
            computer,
            agent,
            project,
            title,
            timestamp_start,
            timestamp_end,
            conversation_text,
            message_count,
            metadata,
            created_at,
            updated_at,
            summary,
            human_email,
            visibility,
            command,
            slug,
            is_worker,
            derivation_version
        FROM mirrors
        WHERE {" AND ".join(clauses)}
        ORDER BY
            CASE
                WHEN :session_id_exact IS NOT NULL AND session_id = :session_id_exact THEN 0
                WHEN :session_id_exact IS NOT NULL AND session_id LIKE :session_id_prefix THEN 1
                ELSE 0
            END,
            LENGTH(session_id),
            updated_at DESC
        LIMIT 1
    """

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


def upsert_mirror(record: MirrorRecord, *, db: str | Path | None = None) -> None:
    """Insert or update a mirror row."""
    if not record.source_identity:
        msg = "MirrorRecord.source_identity is required"
        raise ValueError(msg)

    metadata_json = json.dumps(record.metadata, sort_keys=True)
    payload = {
        "agent": record.agent,
        "command": record.command,
        "computer": record.computer,
        "content": record.conversation_text,
        "created_at": record.created_at,
        "derivation_version": record.derivation_version,
        "human_email": record.human_email,
        "is_worker": 1 if record.is_worker else 0,
        "message_count": record.message_count,
        "metadata": metadata_json,
        "project": record.project,
        "session_id": record.session_id,
        "slug": record.slug,
        "source_identity": record.source_identity,
        "summary": record.summary,
        "timestamp_end": record.timestamp_end,
        "timestamp_start": record.timestamp_start,
        "title": record.title,
        "updated_at": record.updated_at,
        "visibility": record.visibility,
    }
    with _get_rw_engine(db).begin() as conn:
        conn.execute(
            text(
                """
            INSERT INTO mirrors (
                session_id,
                source_identity,
                computer,
                agent,
                project,
                title,
                timestamp_start,
                timestamp_end,
                conversation_text,
                message_count,
                metadata,
                created_at,
                updated_at,
                summary,
                human_email,
                visibility,
                command,
                slug,
                is_worker,
                derivation_version
            )
            VALUES (
                :session_id,
                :source_identity,
                :computer,
                :agent,
                :project,
                :title,
                :timestamp_start,
                :timestamp_end,
                :content,
                :message_count,
                :metadata,
                :created_at,
                :updated_at,
                :summary,
                :human_email,
                :visibility,
                :command,
                :slug,
                :is_worker,
                :derivation_version
            )
            ON CONFLICT(source_identity) DO UPDATE SET
                session_id = :session_id,
                computer = :computer,
                agent = :agent,
                project = :project,
                title = :title,
                timestamp_start = :timestamp_start,
                timestamp_end = :timestamp_end,
                conversation_text = :content,
                message_count = :message_count,
                metadata = :metadata,
                updated_at = :updated_at,
                summary = :summary,
                human_email = :human_email,
                visibility = :visibility,
                command = :command,
                slug = :slug,
                is_worker = :is_worker,
                derivation_version = :derivation_version
            """
            ),
            payload,
        )


def delete_mirror(
    session_id: str | None = None,
    *,
    db: str | Path | None = None,
    source_identity: str | None = None,
) -> None:
    """Delete a mirror row if it exists."""
    if not session_id and not source_identity:
        return
    with _get_rw_engine(db).begin() as conn:
        if source_identity:
            conn.execute(
                text("DELETE FROM mirrors WHERE source_identity = :source_identity"),
                {"source_identity": source_identity},
            )
        else:
            conn.execute(text("DELETE FROM mirrors WHERE session_id = :session_id"), {"session_id": session_id})


def _apply_role_filter(
    clauses: list[str],
    params: dict[str, object],  # guard: loose-dict - SQL bind params are mutated by caller filters.
    caller_email: str | None,
    caller_role: str | None,
) -> None:
    """Apply role-based WHERE clauses for history access control."""
    if caller_role is None or caller_role == HUMAN_ROLE_ADMIN:
        return
    if caller_role == HUMAN_ROLE_MEMBER:
        clauses.append("(human_email = :caller_email OR visibility = 'shared')")
        params["caller_email"] = caller_email
    else:
        clauses.append("human_email = :caller_email")
        params["caller_email"] = caller_email


def list_mirrors(
    *,
    limit: int = 20,
    project: str | None = None,
    identity: str | None = None,
    caller_email: str | None = None,
    caller_role: str | None = None,
    db: str | Path | None = None,
) -> list[MirrorRecord]:
    """List mirror records with optional filtering and role-based access control."""
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}  # guard: loose-dict - optional filters add bind keys.

    if identity:
        clauses.append("(human_email = :identity OR source_identity = :identity)")
        params["identity"] = identity
    if project:
        clauses.append("project = :project")
        params["project"] = project

    _apply_role_filter(clauses, params, caller_email, caller_role)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    sql = f"""
        SELECT
            session_id, source_identity, computer, agent, project, title,
            timestamp_start, timestamp_end, conversation_text, message_count,
            metadata, created_at, updated_at, summary, human_email, visibility,
            command, slug, is_worker, derivation_version
        FROM mirrors
        {where}
        ORDER BY COALESCE(timestamp_start, updated_at) DESC
        LIMIT :limit
    """

    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return []
        raise

    return [_mirror_record_from_row(row) for row in rows]


def get_session_context(
    *,
    session_id: str | None = None,
    transcript_path: str | None = None,
) -> SessionMirrorContext | None:
    """Look up a session row from the main DB by session id or transcript path."""
    if not session_id and not transcript_path:
        return None

    clauses: list[str] = []
    params: dict[str, object] = {  # guard: loose-dict - session lookup binds depend on provided selectors.
        "order_session_id": session_id or ""
    }
    if session_id:
        clauses.append("session_id = :session_id")
        params["session_id"] = session_id
    if transcript_path:
        clauses.append("native_log_file = :transcript_path")
        params["transcript_path"] = transcript_path
    sql = f"""
        SELECT session_id, computer_name, active_agent, project_path, native_log_file,
               human_email, visibility, last_input_origin, adapter_metadata
        FROM sessions
        WHERE {" OR ".join(clauses)}
        ORDER BY CASE WHEN session_id = :order_session_id THEN 0 ELSE 1 END, created_at DESC
        LIMIT 1
    """

    try:
        with _get_main_ro_engine().connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise

    if row is None:
        return None

    return SessionMirrorContext(
        session_id=str(row["session_id"]),
        computer=str(row["computer_name"] or ""),
        agent=_optional_str(row.get("active_agent")),
        project=str(row["project_path"] or ""),
        transcript_path=_optional_str(row.get("native_log_file")),
        human_email=_optional_str(row.get("human_email")),
        visibility=_optional_str(row.get("visibility")),
        last_input_origin=_optional_str(row.get("last_input_origin")),
        adapter_metadata_json=_optional_str(row.get("adapter_metadata")),
    )


@dataclass(frozen=True)
class MirrorTranscriptState:
    """Per-transcript mirror state consulted during reconciliation skip checks."""

    source_identity: str | None
    updated_at: str
    derivation_version: int


@dataclass(frozen=True)
class OrphanMirror:
    """A stored mirror whose transcript file is gone, eligible for in-place re-derivation."""

    session_id: str
    source_identity: str
    agent: str
    title: str
    conversation_text: str
    transcript_path: str | None
    derivation_version: int


def get_mirror_state_by_transcript(db: str | Path | None = None) -> dict[str, MirrorTranscriptState]:
    """Return transcript-path keyed mirror state for reconciliation."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = (
                conn.execute(text("SELECT source_identity, metadata, updated_at, derivation_version FROM mirrors"))
                .mappings()
                .all()
            )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return {}
        raise

    state: dict[str, MirrorTranscriptState] = {}
    for row in rows:
        metadata = _parse_metadata(row.get("metadata"))
        transcript_path = metadata.get("transcript_path")
        updated_at = _optional_str(row.get("updated_at"))
        if not isinstance(transcript_path, str) or not transcript_path or updated_at is None:
            continue
        state[transcript_path] = MirrorTranscriptState(
            source_identity=_optional_str(row.get("source_identity")),
            updated_at=updated_at,
            derivation_version=_int_value(row.get("derivation_version")),
        )
    return state


def get_stale_mirrors(derivation_version: int, *, db: str | Path | None = None) -> list[OrphanMirror]:
    """Return mirrors whose derivation_version is older than the given version."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = (
                conn.execute(
                    text(
                        """
                        SELECT session_id, source_identity, agent, title, conversation_text,
                               metadata, derivation_version
                        FROM mirrors
                        WHERE derivation_version < :derivation_version
                        """
                    ),
                    {"derivation_version": derivation_version},
                )
                .mappings()
                .all()
            )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return []
        raise

    stale: list[OrphanMirror] = []
    for row in rows:
        source_identity = _optional_str(row.get("source_identity"))
        if source_identity is None:
            continue
        metadata = _parse_metadata(row.get("metadata"))
        transcript_path = metadata.get("transcript_path")
        stale.append(
            OrphanMirror(
                session_id=str(row["session_id"]),
                source_identity=source_identity,
                agent=str(row.get("agent") or ""),
                title=str(row.get("title") or ""),
                conversation_text=str(row.get("conversation_text") or ""),
                transcript_path=transcript_path if isinstance(transcript_path, str) and transcript_path else None,
                derivation_version=_int_value(row.get("derivation_version")),
            )
        )
    return stale


def update_mirror_derivation(
    source_identity: str,
    *,
    title: str,
    command: str | None,
    slug: str | None,
    is_worker: bool,
    derivation_version: int,
    db: str | Path | None = None,
) -> None:
    """Update an existing mirror's derived classification fields in place."""
    with _get_rw_engine(db).begin() as conn:
        conn.execute(
            text(
                """
                UPDATE mirrors SET
                    title = :title,
                    command = :command,
                    slug = :slug,
                    is_worker = :is_worker,
                    derivation_version = :derivation_version
                WHERE source_identity = :source_identity
                """
            ),
            {
                "command": command,
                "derivation_version": derivation_version,
                "is_worker": 1 if is_worker else 0,
                "slug": slug,
                "source_identity": source_identity,
                "title": title,
            },
        )


def get_mirror_tombstone(source_identity: str, *, db: str | Path | None = None) -> MirrorTombstoneRecord | None:
    """Fetch a tombstone by source identity."""
    try:
        with _get_ro_engine(db).connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                SELECT source_identity, agent, transcript_path, file_size, file_mtime, created_at
                FROM mirror_tombstones
                WHERE source_identity = :source_identity
                """
                    ),
                    {"source_identity": source_identity},
                )
                .mappings()
                .first()
            )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise

    if row is None:
        return None

    return _tombstone_from_row(row)


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
