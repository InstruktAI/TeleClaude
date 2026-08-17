"""Sync helpers and module-level utilities.

These are standalone functions, not class methods.
"""

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SqlSession
from sqlmodel import select

from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.db.connection_factory import create_sync_db_engine

from .. import db_models

if TYPE_CHECKING:
    from teleclaude.core.models import Session


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
                if "no such table" in str(exc).lower():
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
                if "no such table" in str(exc).lower():
                    return None
                raise
    finally:
        engine.dispose()


def get_session_ids_by_native_sync(db_path: str, native_session_ids: Sequence[str]) -> dict[str, str]:
    """Map native ids to the earliest TeleClaude session record, including closed rows."""
    if not native_session_ids:
        return {}
    engine = create_sync_db_engine(db_path)
    try:
        with SqlSession(engine) as session:
            statement = (
                select(db_models.Session.native_session_id, db_models.Session.session_id)
                .where(db_models.Session.native_session_id.in_(native_session_ids))
                .order_by(db_models.Session.created_at.asc())
            )
            rows = session.exec(statement).all()
            resolved: dict[str, str] = {}
            for native_session_id, session_id in rows:
                if native_session_id and native_session_id not in resolved:
                    resolved[str(native_session_id)] = str(session_id)
            return resolved
    finally:
        engine.dispose()


def _parse_iso_utc(value: str) -> datetime | None:
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def read_agent_availability_sync(db_path: str, agent: str, *, timeout_s: float = 0.2) -> bool:
    """Sync helper to probe agent availability from the main DB.

    Cold-path read used by sub-CLIs that run without a daemon-managed Db
    instance. Fail-open: missing DB/table/row, contention beyond timeout, or
    any sqlite error all return True so dispatch is never blocked by an
    unreachable availability table.

    Mirrors the expiry semantics of the async ``Db.get_agent_availability``:
    an expired ``unavailable_until`` overrides the ``available`` flag, and an
    expired ``degraded_until`` clears a ``degraded`` reason. Without these
    checks an agent stays excluded after its TTL has elapsed.
    """
    if not Path(db_path).exists():
        return True
    try:
        with sqlite3.connect(db_path, timeout=timeout_s) as conn:
            row = conn.execute(
                "SELECT available, unavailable_until, degraded_until, reason "  # guard: raw-sql
                "FROM agent_availability WHERE agent = ?",
                (agent,),
            ).fetchone()
    except sqlite3.Error:
        return True

    if row is None:
        return True

    available_raw, unavailable_until, degraded_until, reason = row
    now = datetime.now(UTC)

    if isinstance(unavailable_until, str) and unavailable_until.strip():
        parsed = _parse_iso_utc(unavailable_until)
        if parsed is not None and parsed <= now:
            return True

    if isinstance(reason, str) and reason.startswith("degraded"):
        if isinstance(degraded_until, str) and degraded_until.strip():
            parsed_degraded = _parse_iso_utc(degraded_until)
            if parsed_degraded is not None and parsed_degraded <= now:
                return True
        return False

    return bool(available_raw)


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


class SessionIdentityError(ValueError):
    """Raised when a session has no resolvable identity."""


def resolve_session_principal(session: "Session") -> tuple[str, str]:
    """Resolve the principal identity for a session.

    Returns (principal, role) where role is informational only — system sessions
    get their authoritative role from session.system_role, not from this function.

    Rules:
    - Inherited principal (session.principal set by parent): reuse it.
    - Human session (human_email present): principal="human:<email>".
    - System session (session.system_role present): principal="system:<session_id>".
    - No identity: raises SessionIdentityError (401).
    """
    if session.principal:
        return session.principal, session.human_role or HUMAN_ROLE_CUSTOMER
    if session.human_email:
        principal = f"human:{session.human_email}"
        role = session.human_role or HUMAN_ROLE_CUSTOMER
        return principal, role
    # System session — only if explicitly created with a system_role.
    if session.system_role:
        principal = f"system:{session.session_id}"
        return principal, session.system_role
    raise SessionIdentityError(
        f"Session {session.session_id} has no identity: "
        "no principal, no human_email, no system_role. "
        "Authentication required."
    )
