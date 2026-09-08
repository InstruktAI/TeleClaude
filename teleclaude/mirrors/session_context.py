"""Session-record lookup for mirror classification.

Resolves the main ``teleclaude.db`` ``sessions`` row a mirror's classification,
command, slug, and title come from — the sole source ``generator.py``,
``worker.py``, and ``processors.py`` consult before generating or realigning a
mirror.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from teleclaude import paths as tc_paths
from teleclaude.core.db.connection_factory import create_sync_db_engine

from .store import _is_missing_table_error, _optional_str, _read_only_sqlite_uri

_main_ro_engines: dict[str, Engine] = {}


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
    system_role: str | None = None
    command: str | None = None
    working_slug: str | None = None
    title: str | None = None


def _get_main_ro_engine() -> Engine:
    """Return the cached read-only main teleclaude.db engine for session lookups."""
    target = _read_only_sqlite_uri(str(tc_paths.MAIN_DB_PATH.resolve()))
    engine = _main_ro_engines.get(target)
    if engine is None:
        engine = create_sync_db_engine(target)
        _main_ro_engines[target] = engine
    return engine


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
               human_email, visibility, last_input_origin, adapter_metadata,
               system_role, command, working_slug, title
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
        system_role=_optional_str(row.get("system_role")),
        command=_optional_str(row.get("command")),
        working_slug=_optional_str(row.get("working_slug")),
        title=_optional_str(row.get("title")),
    )
