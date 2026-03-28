"""Storage and query helpers for conversation mirrors."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from teleclaude import paths as tc_paths
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_local_datetime, parse_iso_datetime

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_schema_initialized: set[str] = set()


@dataclass(frozen=True)
class MirrorSearchResult:  # pylint: disable=too-many-instance-attributes
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
class MirrorRecord:  # pylint: disable=too-many-instance-attributes
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
class SessionMirrorContext:  # pylint: disable=too-many-instance-attributes
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
    _migrate_add_mirror_columns(conn)
    _schema_initialized.add(path)


def _migrate_add_mirror_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add summary, human_email, visibility to existing mirrors tables."""
    for stmt in (
        "ALTER TABLE mirrors ADD COLUMN summary TEXT",
        "ALTER TABLE mirrors ADD COLUMN human_email TEXT",
        "ALTER TABLE mirrors ADD COLUMN visibility TEXT DEFAULT 'private'",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email)")


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
    visibility TEXT DEFAULT 'private'
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


def _connect_rw(db: str | Path | None = None) -> sqlite3.Connection:
    path = str(Path(db).expanduser()) if db is not None else str(tc_paths.MIRRORS_DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    _ensure_schema(conn, path)
    return conn


def _connect_ro(db: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db).expanduser().resolve() if db is not None else tc_paths.MIRRORS_DB_PATH.resolve()
    # Ensure schema and migrations are applied (also creates DB if missing).
    if str(resolved) not in _schema_initialized:
        _connect_rw(db).close()
    uri = f"file:{quote(str(resolved))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


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


def _topic_for_row(row: sqlite3.Row) -> str:
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


def search_mirrors(  # pylint: disable=too-many-arguments,too-many-locals
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

    clauses = ["mirrors_fts MATCH ?"]
    params: list[object] = [match_query]
    agent_values = _agent_values(agents)
    if agent_values:
        placeholders = ", ".join("?" for _ in agent_values)
        clauses.append(f"mirrors.agent IN ({placeholders})")
        params.extend(agent_values)
    if computers:
        placeholders = ", ".join("?" for _ in computers)
        clauses.append(f"mirrors.computer IN ({placeholders})")
        params.extend(computers)
    _apply_role_filter(clauses, params, caller_email, caller_role)
    params.append(limit)

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
        LIMIT ?
    """

    try:
        with _connect_ro(db) as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise

    results: list[MirrorSearchResult] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        results.append(
            MirrorSearchResult(
                session_id=str(row["session_id"]),
                computer=str(row["computer"]),
                agent=str(row["agent"]),
                project=str(row["project"]),
                title=str(row["title"] or ""),
                sort_timestamp=str(row["sort_timestamp"] or ""),
                timestamp=_format_search_timestamp(row["sort_timestamp"]),
                topic=_topic_for_row(row),
                conversation_text=str(row["conversation_text"] or ""),
                metadata=metadata if isinstance(metadata, dict) else {},
                human_email=str(row["human_email"]) if row["human_email"] else None,
                visibility=str(row["visibility"] or "private"),
                source_identity=str(row["source_identity"]) if row["source_identity"] else None,
            )
        )
    return results


def get_mirror(  # pylint: disable=too-many-arguments
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
    params: list[object]
    if source_identity:
        clauses = ["source_identity = ?"]
        params = [source_identity]
    elif session_id:
        clauses = ["(session_id = ? OR session_id LIKE ?)"]
        params = [session_id, f"{session_id}%"]
        if computer:
            clauses.append("computer = ?")
            params.append(computer)
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
            visibility
        FROM mirrors
        WHERE {" AND ".join(clauses)}
        ORDER BY
            CASE
                WHEN ? IS NOT NULL AND session_id = ? THEN 0
                WHEN ? IS NOT NULL AND session_id LIKE ? THEN 1
                ELSE 0
            END,
            LENGTH(session_id),
            updated_at DESC
        LIMIT 1
    """
    params.extend([session_id, session_id, session_id, f"{session_id}%" if session_id else ""])

    try:
        with _connect_ro(db) as conn:
            row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise

    if row is None:
        return None

    try:
        metadata = json.loads(row["metadata"] or "{}")
    except json.JSONDecodeError:
        metadata = {}

    return MirrorRecord(
        session_id=str(row["session_id"]),
        source_identity=str(row["source_identity"]) if row["source_identity"] else None,
        computer=str(row["computer"]),
        agent=str(row["agent"]),
        project=str(row["project"]),
        title=str(row["title"] or ""),
        timestamp_start=row["timestamp_start"],
        timestamp_end=row["timestamp_end"],
        conversation_text=str(row["conversation_text"] or ""),
        message_count=int(row["message_count"] or 0),
        metadata=metadata if isinstance(metadata, dict) else {},
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        summary=str(row["summary"]) if row["summary"] else None,
        human_email=str(row["human_email"]) if row["human_email"] else None,
        visibility=str(row["visibility"] or "private"),
    )


def upsert_mirror(record: MirrorRecord, *, db: str | Path | None = None) -> None:
    """Insert or update a mirror row."""
    if not record.source_identity:
        msg = "MirrorRecord.source_identity is required"
        raise ValueError(msg)

    metadata_json = json.dumps(record.metadata, sort_keys=True)
    payload = (
        record.session_id,
        record.source_identity,
        record.computer,
        record.agent,
        record.project,
        record.title,
        record.timestamp_start,
        record.timestamp_end,
        record.conversation_text,
        record.message_count,
        metadata_json,
        record.created_at,
        record.updated_at,
        record.summary,
        record.human_email,
        record.visibility,
        record.session_id,
        record.computer,
        record.agent,
        record.project,
        record.title,
        record.timestamp_start,
        record.timestamp_end,
        record.conversation_text,
        record.message_count,
        metadata_json,
        record.updated_at,
        record.summary,
        record.human_email,
        record.visibility,
    )
    with _connect_rw(db) as conn:
        conn.execute(
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
                visibility
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_identity) DO UPDATE SET
                session_id = ?,
                computer = ?,
                agent = ?,
                project = ?,
                title = ?,
                timestamp_start = ?,
                timestamp_end = ?,
                conversation_text = ?,
                message_count = ?,
                metadata = ?,
                updated_at = ?,
                summary = ?,
                human_email = ?,
                visibility = ?
            """,
            payload,
        )
        conn.commit()


def delete_mirror(
    session_id: str | None = None,
    *,
    db: str | Path | None = None,
    source_identity: str | None = None,
) -> None:
    """Delete a mirror row if it exists."""
    if not session_id and not source_identity:
        return
    with _connect_rw(db) as conn:
        if source_identity:
            conn.execute("DELETE FROM mirrors WHERE source_identity = ?", (source_identity,))
        else:
            conn.execute("DELETE FROM mirrors WHERE session_id = ?", (session_id,))
        conn.commit()


def _apply_role_filter(
    clauses: list[str],
    params: list[object],
    caller_email: str | None,
    caller_role: str | None,
) -> None:
    """Apply role-based WHERE clauses for history access control."""
    if caller_role is None or caller_role == "admin":
        return
    if caller_role == "member":
        clauses.append("(human_email = ? OR visibility = 'shared')")
        params.append(caller_email)
    else:
        clauses.append("human_email = ?")
        params.append(caller_email)


def list_mirrors(  # pylint: disable=too-many-arguments,too-many-locals
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
    params: list[object] = []

    if identity:
        clauses.append("(human_email = ? OR source_identity = ?)")
        params.extend([identity, identity])
    if project:
        clauses.append("project = ?")
        params.append(project)

    _apply_role_filter(clauses, params, caller_email, caller_role)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    sql = f"""
        SELECT
            session_id, source_identity, computer, agent, project, title,
            timestamp_start, timestamp_end, conversation_text, message_count,
            metadata, created_at, updated_at, summary, human_email, visibility
        FROM mirrors
        {where}
        ORDER BY COALESCE(timestamp_start, updated_at) DESC
        LIMIT ?
    """

    try:
        with _connect_ro(db) as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise

    results: list[MirrorRecord] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        results.append(
            MirrorRecord(
                session_id=str(row["session_id"]),
                source_identity=str(row["source_identity"]) if row["source_identity"] else None,
                computer=str(row["computer"]),
                agent=str(row["agent"]),
                project=str(row["project"]),
                title=str(row["title"] or ""),
                timestamp_start=row["timestamp_start"],
                timestamp_end=row["timestamp_end"],
                conversation_text=str(row["conversation_text"] or ""),
                message_count=int(row["message_count"] or 0),
                metadata=metadata if isinstance(metadata, dict) else {},
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                summary=str(row["summary"]) if row["summary"] else None,
                human_email=str(row["human_email"]) if row["human_email"] else None,
                visibility=str(row["visibility"] or "private"),
            )
        )
    return results


def _connect_main_ro() -> sqlite3.Connection:
    """Read-only connection to the main teleclaude.db for session lookups."""
    path = tc_paths.MAIN_DB_PATH.resolve()
    uri = f"file:{quote(str(path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_session_context(
    *,
    session_id: str | None = None,
    transcript_path: str | None = None,
) -> SessionMirrorContext | None:
    """Look up a session row from the main DB by session id or transcript path."""
    if not session_id and not transcript_path:
        return None

    clauses: list[str] = []
    params: list[object] = []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if transcript_path:
        clauses.append("native_log_file = ?")
        params.append(transcript_path)
    sql = f"""
        SELECT session_id, computer_name, active_agent, project_path, native_log_file,
               human_email, visibility, last_input_origin, adapter_metadata
        FROM sessions
        WHERE {" OR ".join(clauses)}
        ORDER BY CASE WHEN session_id = ? THEN 0 ELSE 1 END, created_at DESC
        LIMIT 1
    """
    params.append(session_id or "")

    try:
        with _connect_main_ro() as conn:
            row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise

    if row is None:
        return None

    return SessionMirrorContext(
        session_id=str(row["session_id"]),
        computer=str(row["computer_name"] or ""),
        agent=row["active_agent"],
        project=str(row["project_path"] or ""),
        transcript_path=row["native_log_file"],
        human_email=row["human_email"] if row["human_email"] else None,
        visibility=row["visibility"] if row["visibility"] else None,
        last_input_origin=row["last_input_origin"] if row["last_input_origin"] else None,
        adapter_metadata_json=row["adapter_metadata"] if row["adapter_metadata"] else None,
    )


def get_mirror_state_by_transcript(db: str | Path | None = None) -> dict[str, tuple[str | None, str]]:
    """Return transcript-path keyed mirror state for reconciliation."""
    try:
        with _connect_ro(db) as conn:
            rows = conn.execute("SELECT source_identity, metadata, updated_at FROM mirrors").fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {}
        raise

    state: dict[str, tuple[str | None, str]] = {}
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict):
            continue
        transcript_path = metadata.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path:
            source_identity = str(row["source_identity"]) if row["source_identity"] else None
            state[transcript_path] = (source_identity, str(row["updated_at"]))
    return state


def get_mirror_tombstone(source_identity: str, *, db: str | Path | None = None) -> MirrorTombstoneRecord | None:
    """Fetch a tombstone by source identity."""
    try:
        with _connect_ro(db) as conn:
            row = conn.execute(
                """
                SELECT source_identity, agent, transcript_path, file_size, file_mtime, created_at
                FROM mirror_tombstones
                WHERE source_identity = ?
                """,
                (source_identity,),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise

    if row is None:
        return None

    return MirrorTombstoneRecord(
        source_identity=str(row["source_identity"]),
        agent=str(row["agent"]),
        transcript_path=str(row["transcript_path"]),
        file_size=int(row["file_size"]),
        file_mtime=str(row["file_mtime"]),
        created_at=str(row["created_at"]),
    )


def upsert_mirror_tombstone(record: MirrorTombstoneRecord, *, db: str | Path | None = None) -> None:
    """Insert or update an empty-transcript tombstone."""
    with _connect_rw(db) as conn:
        conn.execute(
            """
            INSERT INTO mirror_tombstones (
                source_identity,
                agent,
                transcript_path,
                file_size,
                file_mtime,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_identity) DO UPDATE SET
                agent = excluded.agent,
                transcript_path = excluded.transcript_path,
                file_size = excluded.file_size,
                file_mtime = excluded.file_mtime,
                created_at = excluded.created_at
            """,
            (
                record.source_identity,
                record.agent,
                record.transcript_path,
                record.file_size,
                record.file_mtime,
                record.created_at,
            ),
        )
        conn.commit()


def delete_mirror_tombstone(source_identity: str, *, db: str | Path | None = None) -> None:
    """Delete a tombstone if it exists."""
    with _connect_rw(db) as conn:
        conn.execute("DELETE FROM mirror_tombstones WHERE source_identity = ?", (source_identity,))
        conn.commit()
