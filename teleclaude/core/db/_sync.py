"""Sync helpers and module-level utilities.

These are standalone functions, not class methods.
"""

from typing import TYPE_CHECKING

from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_CUSTOMER

from .. import db_models

if TYPE_CHECKING:
    from teleclaude.core.models import Session


def _fetch_session_id_sync(db_path: str, field: str, value: object) -> str | None:
    """Sync helper for session_id lookups in standalone scripts.

    guard: allow-string-compare
    """
    from sqlalchemy import create_engine, text  # noqa: raw-sql
    from sqlalchemy.exc import OperationalError
    from sqlmodel import Session as SqlSession
    from sqlmodel import select

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

    engine = create_engine(f"sqlite:///{db_path}")
    with SqlSession(engine) as session:
        session.exec(text("PRAGMA journal_mode = WAL"))  # noqa: raw-sql
        session.exec(text("PRAGMA busy_timeout = 5000"))  # noqa: raw-sql
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


def get_session_id_by_field_sync(db_path: str, field: str, value: object) -> str | None:
    """Sync helper for lookups in standalone scripts (hook receiver, telec)."""
    return _fetch_session_id_sync(db_path, field, value)


def get_session_id_by_tmux_name_sync(db_path: str, tmux_name: str) -> str | None:
    """Sync helper to find session_id by tmux session name."""
    return _fetch_session_id_sync(db_path, "tmux_session_name", tmux_name)


def get_session_field_sync(db_path: str, session_id: str, field: str) -> object | None:
    """Sync helper to fetch a single field from a session by ID."""
    from sqlalchemy import create_engine, text  # noqa: raw-sql
    from sqlalchemy.exc import OperationalError
    from sqlmodel import Session as SqlSession
    from sqlmodel import select

    # Validate field against Session model attributes
    model_fields = getattr(db_models.Session, "model_fields", None)
    if isinstance(model_fields, dict):
        valid_fields = set(model_fields.keys())
    else:
        fields_fallback = getattr(db_models.Session, "__fields__", {})
        valid_fields = set(fields_fallback.keys()) if isinstance(fields_fallback, dict) else set()
    if field not in valid_fields:
        raise ValueError(f"Invalid field '{field}' for Session lookup. Valid fields: {sorted(valid_fields)}")

    engine = create_engine(f"sqlite:///{db_path}")
    with SqlSession(engine) as session:
        session.exec(text("PRAGMA journal_mode = WAL"))  # noqa: raw-sql
        session.exec(text("PRAGMA busy_timeout = 5000"))  # noqa: raw-sql
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


def resolve_session_principal(session: "Session") -> tuple[str, str]:
    """Resolve the (principal, role) pair for a session at token issuance time.

    Rules:
    - Inherited principal (session.principal set by parent): reuse it with the
      session's human_role (preserving the identity chain across agent spawns).
    - Human session (human_email present): principal="human:<email>", role=human_role or "customer"
    - System/job session: principal="system:<session_id>", role="admin"

    The full session_id is used as the stable identifier for system principals
    to ensure traceability without truncation.
    """
    if session.principal:
        return session.principal, session.human_role or HUMAN_ROLE_CUSTOMER
    if session.human_email:
        principal = f"human:{session.human_email}"
        role = session.human_role or HUMAN_ROLE_CUSTOMER
        return principal, role
    # System/job session — use full session_id as the stable identifier.
    principal = f"system:{session.session_id}"
    return principal, session.human_role or HUMAN_ROLE_ADMIN
