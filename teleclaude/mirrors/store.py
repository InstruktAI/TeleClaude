"""Storage and query helpers for conversation mirrors."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_local_datetime, parse_iso_datetime

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class MirrorSearchResult:
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


@dataclass(frozen=True)
class MirrorRecord:
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


@dataclass(frozen=True)
class SessionMirrorContext:
    session_id: str
    computer: str
    agent: str | None
    project: str
    transcript_path: str | None


def resolve_db_path(db: object | None = None) -> str:
    """Resolve a database path from env/config or a db-like object."""
    env_path = os.getenv("TELECLAUDE_DB_PATH")
    if db is None:
        return env_path or config.database.path
    if isinstance(db, Path):
        return str(db.expanduser())
    if isinstance(db, str):
        return str(Path(db).expanduser())
    db_path = getattr(db, "db_path", None)
    if isinstance(db_path, str):
        return db_path
    if isinstance(db_path, Path):
        return str(db_path.expanduser())
    if env_path:
        return env_path
    return config.database.path


def _connect_rw(db: object | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_ro(db: object | None = None) -> sqlite3.Connection:
    path = Path(resolve_db_path(db)).expanduser().resolve()
    uri = f"file:{quote(str(path))}?mode=ro"
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


def search_mirrors(
    query: str,
    agents: Sequence[AgentName | str],
    *,
    limit: int = 20,
    db: object | None = None,
    computers: Sequence[str] | None = None,
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
            mirrors.metadata
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
            )
        )
    return results


def get_mirror(session_id: str, *, db: object | None = None, computer: str | None = None) -> MirrorRecord | None:
    """Fetch a mirror by exact or prefix session id."""
    clauses = ["(session_id = ? OR session_id LIKE ?)"]
    params: list[object] = [session_id, f"{session_id}%"]
    if computer:
        clauses.append("computer = ?")
        params.append(computer)

    sql = f"""
        SELECT
            session_id,
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
            updated_at
        FROM mirrors
        WHERE {" AND ".join(clauses)}
        ORDER BY CASE WHEN session_id = ? THEN 0 ELSE 1 END, LENGTH(session_id)
        LIMIT 1
    """
    params.append(session_id)

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
    )


def upsert_mirror(record: MirrorRecord, *, db: object | None = None) -> None:
    """Insert or update a mirror row."""
    payload = (
        record.session_id,
        record.computer,
        record.agent,
        record.project,
        record.title,
        record.timestamp_start,
        record.timestamp_end,
        record.conversation_text,
        record.message_count,
        json.dumps(record.metadata, sort_keys=True),
        record.created_at,
        record.updated_at,
        record.computer,
        record.agent,
        record.project,
        record.title,
        record.timestamp_start,
        record.timestamp_end,
        record.conversation_text,
        record.message_count,
        json.dumps(record.metadata, sort_keys=True),
        record.updated_at,
    )
    with _connect_rw(db) as conn:
        conn.execute(
            """
            INSERT INTO mirrors (
                session_id,
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
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                computer = ?,
                agent = ?,
                project = ?,
                title = ?,
                timestamp_start = ?,
                timestamp_end = ?,
                conversation_text = ?,
                message_count = ?,
                metadata = ?,
                updated_at = ?
            """,
            payload,
        )
        conn.commit()


def delete_mirror(session_id: str, *, db: object | None = None) -> None:
    """Delete a mirror row if it exists."""
    with _connect_rw(db) as conn:
        conn.execute("DELETE FROM mirrors WHERE session_id = ?", (session_id,))
        conn.commit()


def get_session_context(
    *,
    session_id: str | None = None,
    transcript_path: str | None = None,
    db: object | None = None,
) -> SessionMirrorContext | None:
    """Look up a session row by session id or transcript path."""
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
        SELECT session_id, computer_name, active_agent, project_path, native_log_file
        FROM sessions
        WHERE {" OR ".join(clauses)}
        ORDER BY CASE WHEN session_id = ? THEN 0 ELSE 1 END, created_at DESC
        LIMIT 1
    """
    params.append(session_id or "")

    try:
        with _connect_ro(db) as conn:
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
    )


def get_mirror_state_by_transcript(db: object | None = None) -> dict[str, tuple[str, str]]:
    """Return transcript-path keyed mirror state for reconciliation."""
    try:
        with _connect_ro(db) as conn:
            rows = conn.execute("SELECT session_id, metadata, updated_at FROM mirrors").fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {}
        raise

    state: dict[str, tuple[str, str]] = {}
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict):
            continue
        transcript_path = metadata.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path:
            state[transcript_path] = (str(row["session_id"]), str(row["updated_at"]))
    return state
