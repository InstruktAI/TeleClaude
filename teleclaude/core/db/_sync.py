"""Sync helpers and module-level utilities.

These are standalone functions, not class methods.
"""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Engine, text  # guard: raw-sql
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SqlSession
from sqlmodel import select

from teleclaude.caller_identity import SessionIdentityError as SessionIdentityError
from teleclaude.caller_identity import resolve_session_principal as resolve_session_principal
from teleclaude.core.agent_availability import (
    AgentAvailabilityStatus,
    AvailabilityState,
    LaunchOwnership,
    is_launchable,
)
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.core.models import Session as SessionRecord
from teleclaude.core.models._session import SessionField
from teleclaude.core.session_identity_facts import read_session_identity_facts
from teleclaude.core.session_transcript_chain import build_message_chain

from .. import db_models

_NO_SUCH_TABLE_ERROR = "no such table"
_EMPTY_SESSION_TEXT = ""
_SESSION_MIRROR_FACTS_SQL = """\
SELECT session_id, computer_name, active_agent, project_path, subdir, config_subject, subject_owner, native_log_file,
       transcript_files, visibility, last_input_origin, adapter_metadata, system_role,
       command, working_slug, title, initiator_session_id, initiator_computer,
       initiated_by_ai, job, created_at, closed_at, principal, human_email, human_role
FROM sessions
WHERE (:session_id IS NOT NULL AND session_id = :session_id)
   OR (:transcript_path IS NOT NULL AND native_log_file = :transcript_path)
   OR (:transcript_path IS NOT NULL AND EXISTS (
       SELECT 1 FROM json_each(sessions.transcript_files) WHERE value = :transcript_path
   ))
ORDER BY CASE WHEN session_id = :session_id THEN 0 ELSE 1 END, created_at DESC
LIMIT 1
"""
_SESSION_MIRROR_FACTS_LIST_SQL = """\
SELECT session_id, computer_name, active_agent, project_path, subdir, config_subject, subject_owner, native_log_file,
       transcript_files, visibility, last_input_origin, adapter_metadata, system_role,
       command, working_slug, title, initiator_session_id, initiator_computer,
       initiated_by_ai, job, created_at, closed_at, principal, human_email, human_role
FROM sessions
WHERE (native_log_file IS NOT NULL AND native_log_file <> '')
   OR (transcript_files IS NOT NULL AND json_array_length(transcript_files) > 0)
ORDER BY created_at DESC
"""
_SESSION_CLOSES_SQL_PREFIX = "SELECT session_id, closed_at FROM sessions WHERE session_id IN ("
_SESSION_CLOSES_SQL_SUFFIX = ") AND closed_at IS NOT NULL"
_SESSION_EXISTENCE_SQL_PREFIX = "SELECT session_id FROM sessions WHERE session_id IN ("
_SESSION_EXISTENCE_SQL_SUFFIX = ")"
_SESSION_EXISTENCE_CHUNK = 500
_READ_ONLY_URI_SUFFIX = "?mode=ro&uri=true"


@dataclass(frozen=True)
class SessionMirrorFacts:
    """Session-record facts published for durable mirror attribution."""

    session_id: str
    computer_name: str
    active_agent: str | None
    project_path: str | None
    subdir: str | None
    config_subject: str | None
    subject_owner: str | None
    native_log_file: str | None
    transcript_files: tuple[str, ...]
    lineage: tuple[str, ...]
    visibility: str | None
    last_input_origin: str | None
    adapter_metadata: str | None
    system_role: str | None
    command: str | None
    working_slug: str | None
    title: str | None
    initiator_session_id: str | None
    initiator_computer: str | None
    initiated_by_ai: bool | None
    job: str | None
    created_at: str | None
    closed_at: str | None
    identity: SessionRecord


def _session_mirror_facts_engine(db_path: str) -> Engine:
    """Create a read-only engine for session-record publication queries."""
    uri = f"file:{quote(str(Path(db_path).expanduser().resolve()), safe='/')}{_READ_ONLY_URI_SUFFIX}"
    return create_sync_db_engine(uri)


def _optional_session_fact(value: object) -> str | None:
    """Normalize an optional scalar fact from SQLite."""
    return str(value) if value is not None else None


def _session_datetime(value: object) -> datetime | None:
    """Normalize a timestamp into the in-memory session model's type."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _session_mirror_facts(row: Mapping[str, object]) -> SessionMirrorFacts:
    """Convert one SQL row into the published session-mirror record."""
    mapping = row
    raw_transcripts = mapping["transcript_files"]
    parsed_transcripts = json.loads(raw_transcripts) if isinstance(raw_transcripts, str) else []
    transcript_files = tuple(value for value in parsed_transcripts if isinstance(value, str))
    native_log_file = _optional_session_fact(mapping["native_log_file"])
    session_id = str(mapping["session_id"])
    identity = SessionRecord(
        session_id=session_id,
        computer_name=str(mapping["computer_name"] or _EMPTY_SESSION_TEXT),
        tmux_session_name=_EMPTY_SESSION_TEXT,
        title=str(mapping["title"] or _EMPTY_SESSION_TEXT),
        config_subject=_optional_session_fact(mapping[SessionField.CONFIG_SUBJECT.value]),
        subject_owner=_optional_session_fact(mapping[SessionField.SUBJECT_OWNER.value]),
        principal=_optional_session_fact(mapping["principal"]),
        human_email=_optional_session_fact(mapping["human_email"]),
        human_role=_optional_session_fact(mapping["human_role"]),
        system_role=_optional_session_fact(mapping["system_role"]),
        working_slug=_optional_session_fact(mapping["working_slug"]),
        closed_at=_session_datetime(mapping["closed_at"]),
    )
    return SessionMirrorFacts(
        session_id=session_id,
        computer_name=str(mapping["computer_name"] or _EMPTY_SESSION_TEXT),
        active_agent=_optional_session_fact(mapping["active_agent"]),
        project_path=_optional_session_fact(mapping["project_path"]),
        subdir=_optional_session_fact(mapping["subdir"]),
        config_subject=_optional_session_fact(mapping[SessionField.CONFIG_SUBJECT.value]),
        subject_owner=_optional_session_fact(mapping[SessionField.SUBJECT_OWNER.value]),
        native_log_file=native_log_file,
        transcript_files=transcript_files,
        lineage=tuple(
            build_message_chain(raw_transcripts if isinstance(raw_transcripts, str) else None, native_log_file)
        ),
        visibility=_optional_session_fact(mapping["visibility"]),
        last_input_origin=_optional_session_fact(mapping["last_input_origin"]),
        adapter_metadata=_optional_session_fact(mapping["adapter_metadata"]),
        system_role=_optional_session_fact(mapping["system_role"]),
        command=_optional_session_fact(mapping["command"]),
        working_slug=_optional_session_fact(mapping["working_slug"]),
        title=_optional_session_fact(mapping["title"]),
        initiator_session_id=_optional_session_fact(mapping["initiator_session_id"]),
        initiator_computer=_optional_session_fact(mapping["initiator_computer"]),
        initiated_by_ai=(bool(mapping["initiated_by_ai"]) if mapping["initiated_by_ai"] is not None else None),
        job=_optional_session_fact(mapping["job"]),
        created_at=str(mapping["created_at"]) if mapping["created_at"] is not None else None,
        closed_at=str(mapping["closed_at"]) if mapping["closed_at"] is not None else None,
        identity=identity,
    )


def get_session_mirror_facts_sync(
    db_path: str, *, session_id: str | None = None, transcript_path: str | None = None
) -> SessionMirrorFacts | None:
    """Resolve one session by its TeleClaude id or any transcript in its chain."""
    if not session_id and not transcript_path:
        return None
    engine = _session_mirror_facts_engine(db_path)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(_SESSION_MIRROR_FACTS_SQL),  # guard: raw-sql
                    {"session_id": session_id, "transcript_path": transcript_path},
                )
                .mappings()
                .first()
            )
            return _session_mirror_facts(row) if row is not None else None
    except OperationalError as exc:
        if _NO_SUCH_TABLE_ERROR in str(exc).lower():
            return None
        raise
    finally:
        engine.dispose()


def list_session_mirror_facts_sync(db_path: str) -> list[SessionMirrorFacts]:
    """Read every session record with at least one current or predecessor transcript."""
    engine = _session_mirror_facts_engine(db_path)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text(_SESSION_MIRROR_FACTS_LIST_SQL)).mappings().all()  # guard: raw-sql
            return [_session_mirror_facts(row) for row in rows]
    except OperationalError as exc:
        if _NO_SUCH_TABLE_ERROR in str(exc).lower():
            return []
        raise
    finally:
        engine.dispose()


def get_session_closed_at_sync(db_path: str, session_ids: Sequence[str]) -> dict[str, str]:
    """Return close timestamps for the requested session records that have closed."""
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    engine = _session_mirror_facts_engine(db_path)
    try:
        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                f"{_SESSION_CLOSES_SQL_PREFIX}{placeholders}{_SESSION_CLOSES_SQL_SUFFIX}",
                tuple(session_ids),
            ).fetchall()
            return {str(session_id): str(closed_at) for session_id, closed_at in rows}
    except OperationalError as exc:
        if _NO_SUCH_TABLE_ERROR in str(exc).lower():
            return {}
        raise
    finally:
        engine.dispose()


def existing_session_ids_sync(db_path: str, session_ids: Sequence[str]) -> set[str]:
    """Return which of the requested ids have a retained session record, soft-deleted or archived ones included."""
    if not session_ids:
        return set()
    engine = _session_mirror_facts_engine(db_path)
    existing: set[str] = set()
    try:
        with engine.connect() as connection:
            for start in range(0, len(session_ids), _SESSION_EXISTENCE_CHUNK):
                chunk = tuple(session_ids[start : start + _SESSION_EXISTENCE_CHUNK])
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.exec_driver_sql(
                    f"{_SESSION_EXISTENCE_SQL_PREFIX}{placeholders}{_SESSION_EXISTENCE_SQL_SUFFIX}", chunk
                ).fetchall()
                existing.update(str(row[0]) for row in rows)
            return existing
    except OperationalError as exc:
        if _NO_SUCH_TABLE_ERROR in str(exc).lower():
            return set()
        raise
    finally:
        engine.dispose()


def _fetch_session_id_sync(db_path: str, field: str, value: object) -> str | None:
    """Sync helper for session_id lookups in standalone scripts.

    guard: allow-string-compare
    """
    # Validate field against Session model attributes to fail fast on typos.
    model_fields = getattr(db_models.Session, "model_fields", None)
    if isinstance(model_fields, dict):
        valid_fields = set(model_fields.keys())
    else:
        # Backward-compatible fallback for older Pydantic/SQLModel internals.
        fields_fallback = getattr(db_models.Session, "__fields__", {})
        valid_fields = set(fields_fallback.keys()) if isinstance(fields_fallback, dict) else set()
    if field not in valid_fields:
        raise ValueError(f"Invalid field '{field}' for Session lookup. Valid fields: {sorted(valid_fields)}")

    engine = create_sync_db_engine(db_path)
    try:
        with SqlSession(engine) as session:
            column = getattr(db_models.Session, field, None)
            if column is None:
                raise ValueError(f"Invalid field '{field}' for Session lookup")
            stmt = (
                select(db_models.Session.session_id)
                .where(column == value)
                .where(db_models.Session.closed_at.is_(None))
                .order_by(db_models.Session.last_activity.desc())
                .limit(1)
            )
            try:
                row = session.exec(stmt).first()
            except OperationalError as exc:
                if _NO_SUCH_TABLE_ERROR in str(exc).lower():
                    return None
                raise
            return str(row) if row else None
    finally:
        engine.dispose()


def get_session_id_by_field_sync(db_path: str, field: str, value: object) -> str | None:
    """Sync helper for lookups in standalone scripts (hook receiver, telec)."""
    return _fetch_session_id_sync(db_path, field, value)


def get_session_id_by_tmux_name_sync(db_path: str, tmux_name: str) -> str | None:
    """Sync helper to find session_id by tmux session name."""
    return _fetch_session_id_sync(db_path, "tmux_session_name", tmux_name)


def get_session_field_sync(db_path: str, session_id: str, field: str) -> object | None:
    """Sync helper to fetch a single field from a session by ID."""
    # Validate field against Session model attributes
    model_fields = getattr(db_models.Session, "model_fields", None)
    if isinstance(model_fields, dict):
        valid_fields = set(model_fields.keys())
    else:
        fields_fallback = getattr(db_models.Session, "__fields__", {})
        valid_fields = set(fields_fallback.keys()) if isinstance(fields_fallback, dict) else set()
    if field not in valid_fields:
        raise ValueError(f"Invalid field '{field}' for Session lookup. Valid fields: {sorted(valid_fields)}")

    engine = create_sync_db_engine(db_path)
    try:
        with SqlSession(engine) as session:
            column = getattr(db_models.Session, field, None)
            if column is None:
                raise ValueError(f"Invalid field '{field}'")
            stmt = select(column).where(db_models.Session.session_id == session_id)
            try:
                return session.exec(stmt).first()
            except OperationalError as exc:
                if _NO_SUCH_TABLE_ERROR in str(exc).lower():
                    return None
                raise
    finally:
        engine.dispose()


def get_session_identity_sync(db_path: str, session_id: str) -> SessionRecord | None:
    """Load one session's identity-bearing fields from the session record."""
    facts = read_session_identity_facts(db_path, session_id)
    if facts is None:
        return None
    return SessionRecord(
        session_id=facts.session_id,
        computer_name=facts.computer_name,
        tmux_session_name=_EMPTY_SESSION_TEXT,
        title=_EMPTY_SESSION_TEXT,
        principal=facts.principal,
        human_email=facts.human_email,
        human_role=facts.human_role,
        system_role=facts.system_role,
        working_slug=facts.working_slug,
        job=facts.job,
        initiator_session_id=facts.initiator_session_id,
        company=facts.company,
        closed_at=facts.closed_at,
    )


def get_session_company_sync(db_path: str, session_id: str) -> str | None:
    """Load the recorded company from the shared lightweight identity query."""
    facts = read_session_identity_facts(db_path, session_id)
    return facts.company if facts is not None else None


def get_session_ids_by_native_sync(db_path: str, native_session_ids: Sequence[str]) -> dict[str, str]:
    """Map native ids to the newest TeleClaude session record, including closed rows."""
    if not native_session_ids:
        return {}
    engine = create_sync_db_engine(db_path)
    try:
        with SqlSession(engine) as session:
            statement = (
                select(db_models.Session.native_session_id, db_models.Session.session_id)
                .where(db_models.Session.native_session_id.in_(native_session_ids))
                .order_by(db_models.Session.created_at.desc(), db_models.Session.session_id.desc())
            )
            rows = session.exec(statement).all()
            resolved: dict[str, str] = {}
            for native_session_id, session_id in rows:
                if native_session_id and native_session_id not in resolved:
                    resolved[str(native_session_id)] = str(session_id)
            return resolved
    finally:
        engine.dispose()


def read_agent_availability_sync(db_path: str, agent: str, *, timeout_s: float = 0.2) -> bool:
    """Sync helper to probe agent availability from the main DB.

    Cold-path read used by sub-CLIs that run without a daemon-managed Db
    instance. Fail-open: missing DB/table/row, contention beyond timeout, or
    any sqlite error all return True so dispatch is never blocked by an
    unreachable availability table.

    Mirrors the normalized typed state used by async availability reads.
    """
    if not Path(db_path).exists():
        return True
    try:
        with sqlite3.connect(db_path, timeout=timeout_s) as conn:
            row = conn.execute(
                "SELECT status, status_until, reason "  # guard: raw-sql
                "FROM agent_availability WHERE agent = ? AND model = ''",
                (agent,),
            ).fetchone()
    except sqlite3.Error:
        return True

    if row is None:
        return True

    status_raw, status_until, reason = row
    try:
        state = AvailabilityState(
            AgentAvailabilityStatus(str(status_raw)),
            str(status_until) if status_until is not None else None,
            str(reason) if reason is not None else None,
        ).normalized(datetime.now(UTC))
    except ValueError:
        return True
    return is_launchable(state.status, LaunchOwnership.JOB_ROLE)


def get_process_spawn_registry_entry_sync(
    db_path: str, owner: str, *, timeout_s: float = 1.0
) -> db_models.ProcessSpawnRegistryEntry | None:
    """Return one spawn registry entry from a synchronous spawn path."""
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(db_path, timeout=timeout_s) as conn:
        row = conn.execute(
            "SELECT owner, pid, lease_expires_at, registered_at "  # guard: raw-sql
            "FROM process_spawn_registry WHERE owner = ?",
            (owner,),
        ).fetchone()
    if row is None:
        return None
    return db_models.ProcessSpawnRegistryEntry(
        owner=str(row[0]),
        pid=int(row[1]),
        lease_expires_at=str(row[2]),
        registered_at=str(row[3]),
    )


def replace_process_spawn_registry_entry_sync(
    db_path: str,
    *,
    owner: str,
    pid: int,
    lease_expires_at: str,
    registered_at: str | None = None,
    timeout_s: float = 1.0,
) -> db_models.ProcessSpawnRegistryEntry | None:
    """Atomically replace the owner row and return the previous registrant."""
    registered = registered_at or datetime.now(UTC).isoformat()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=timeout_s) as conn:
        row = conn.execute(
            "SELECT owner, pid, lease_expires_at, registered_at "  # guard: raw-sql
            "FROM process_spawn_registry WHERE owner = ?",
            (owner,),
        ).fetchone()
        conn.execute(
            "INSERT INTO process_spawn_registry(owner, pid, lease_expires_at, registered_at) "  # guard: raw-sql
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner) DO UPDATE SET "
            "pid = excluded.pid, "
            "lease_expires_at = excluded.lease_expires_at, "
            "registered_at = excluded.registered_at",
            (owner, pid, lease_expires_at, registered),
        )
        conn.commit()
    if row is None:
        return None
    return db_models.ProcessSpawnRegistryEntry(
        owner=str(row[0]),
        pid=int(row[1]),
        lease_expires_at=str(row[2]),
        registered_at=str(row[3]),
    )


def delete_process_spawn_registry_entry_sync(db_path: str, owner: str, *, timeout_s: float = 1.0) -> None:
    """Delete a spawn registry entry from a synchronous spawn path."""
    if not Path(db_path).exists():
        return
    with sqlite3.connect(db_path, timeout=timeout_s) as conn:
        conn.execute(
            "DELETE FROM process_spawn_registry WHERE owner = ?",  # guard: raw-sql
            (owner,),
        )
        conn.commit()
