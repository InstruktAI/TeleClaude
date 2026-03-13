"""DB engine, memory context, session mapping, and TMUX/headless session resolution."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import db_models
from teleclaude.paths import SESSION_MAP_PATH

logger = get_logger("teleclaude.hooks.receiver")


def _create_sync_engine() -> object:
    """Create a sync SQLAlchemy engine with SQLite PRAGMAs set at connect time."""
    from sqlalchemy import create_engine
    from sqlalchemy import event as sa_event

    engine = create_engine(f"sqlite:///{config.database.path}")

    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()

    return engine


def _get_memory_context(project_name: str, identity_key: str | None = None) -> str:
    """Fetch pre-formatted memory context from local database."""
    try:
        from teleclaude.memory.context import generate_context_sync

        db_path = str(config.database.path)
        return generate_context_sync(project_name, db_path, identity_key=identity_key)
    except Exception:
        return ""


def _get_session_map_path() -> Path:
    return SESSION_MAP_PATH


def _session_map_key(agent: str, native_session_id: str) -> str:
    return f"{agent}:{native_session_id}"


def _load_session_map(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    sources: list[str] = []
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            loaded = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError):
            loaded = {}
        data.update({str(k): str(v) for k, v in loaded.items() if isinstance(k, str) and isinstance(v, str)})
        sources.append(str(path))
    if sources:
        logger.debug("Loaded session map", path=str(path), sources=sources, entries=len(data))
    return data


def _write_session_map_atomic(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _get_cached_session_id(agent: str, native_session_id: str | None) -> str | None:
    if not native_session_id:
        return None
    path = _get_session_map_path()
    data = _load_session_map(path)
    cached = data.get(_session_map_key(agent, native_session_id))
    logger.debug(
        "Session map lookup",
        agent=agent,
        native_session_id=(native_session_id or ""),
        cached_session_id=(cached or ""),
        path=str(path),
        hit=bool(cached),
    )
    return cached


def _get_tmux_contract_tmpdir() -> str:
    tmpdir = os.getenv("TMPDIR") or os.getenv("TMP") or os.getenv("TEMP")
    if not isinstance(tmpdir, str) or not tmpdir.strip():
        raise ValueError("TMUX hook contract violated: TMPDIR/TMP/TEMP is missing")
    return tmpdir


def _is_tmux_contract_session_compatible(session_id: str, native_session_id: str | None, *, agent: str) -> bool:
    """Validate whether a TMUX contract session is still bound to this hook identity.

    Allow native-session rollover for the same active agent (expected during
    start/resume transitions) while rejecting cross-agent/cross-native binding.
    """
    if not native_session_id:
        return True

    from sqlmodel import Session as SqlSession

    try:
        with SqlSession(_create_sync_engine()) as session:
            row = session.get(db_models.Session, session_id)
    except Exception as exc:
        logger.debug(
            "TMUX contract DB lookup skipped (db unavailable)",
            session_id=session_id,
            native_session_id=native_session_id,
            error=str(exc),
        )
        return True

    if not row:
        logger.debug(
            "TMUX contract session not found in DB",
            session_id=session_id,
            native_session_id=native_session_id,
        )
        return False

    if row.closed_at:
        logger.debug(
            "TMUX contract session rejected: closed row",
            session_id=session_id,
            native_session_id=native_session_id,
        )
        return False

    if row.native_session_id and row.native_session_id != native_session_id:
        row_agent = (row.active_agent or "").strip().lower()
        incoming_agent = (agent or "").strip().lower()
        if row_agent and incoming_agent and row_agent == incoming_agent:
            logger.debug(
                "TMUX contract native id rollover accepted for same agent",
                session_id=session_id,
                agent=incoming_agent,
                previous_native_session_id=(row.native_session_id or ""),
                incoming_native_session_id=native_session_id,
            )
            return True
        logger.debug(
            "TMUX contract session rejected: native session id mismatch",
            session_id=session_id,
            contract_native_session_id=(row.native_session_id or ""),
            incoming_native_session_id=native_session_id,
            contract_agent=row_agent,
            incoming_agent=incoming_agent,
        )
        return False

    return True


def _get_tmux_contract_session_id() -> str:
    """Resolve TeleClaude session id from TMUX contract marker file.

    Contract (non-headless):
    - TMUX env var is present
    - TMPDIR/TMP/TEMP is present
    - {temp}/teleclaude_session_id exists and is non-empty
    """
    tmpdir = _get_tmux_contract_tmpdir()

    marker = Path(tmpdir).expanduser() / "teleclaude_session_id"
    try:
        value = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"TMUX hook contract violated: missing session marker at {marker}") from exc

    if not value:
        raise ValueError(f"TMUX hook contract violated: empty session marker at {marker}")

    return value


def _is_headless_route() -> bool:
    """Determine route class for this hook invocation."""
    return not bool(os.getenv("TMUX"))


def _resolve_or_refresh_session_id(
    candidate_session_id: str | None,
    raw_native_session_id: str | None,
    *,
    agent: str,
) -> str | None:
    """Validate cached session id against current DB state.

    Checks only that the session exists and is not closed.  If the DB has a
    stale native_session_id (e.g. after a Claude Code restart), update it to
    the incoming value so future DB lookups also resolve correctly.
    """
    if not candidate_session_id or not raw_native_session_id:
        return candidate_session_id

    from sqlmodel import Session as SqlSession

    try:
        with SqlSession(_create_sync_engine()) as session:
            row = session.get(db_models.Session, candidate_session_id)
            if not row:
                logger.debug(
                    "Invalidating cached session mapping: session row not found",
                    agent=agent,
                    session_id=candidate_session_id,
                    native_session_id=raw_native_session_id,
                )
                return None

            if row.closed_at:
                logger.debug(
                    "Invalidating cached session mapping: session closed",
                    agent=agent,
                    session_id=candidate_session_id,
                    native_session_id=raw_native_session_id,
                )
                return None

            if row.native_session_id and row.native_session_id != raw_native_session_id:
                row.native_session_id = raw_native_session_id
                session.add(row)
                session.commit()
                logger.info(
                    "Updated stale native_session_id in DB",
                    agent=agent,
                    session_id=candidate_session_id,
                    new_native_session_id=raw_native_session_id,
                )

    except Exception as exc:
        logger.debug(
            "Session refresh lookup skipped (db unavailable)",
            agent=agent,
            session_id=candidate_session_id,
            error=str(exc),
        )

    return candidate_session_id


def _find_session_id_by_native(native_session_id: str | None) -> str | None:
    """Look up the latest non-closed session for a native session id."""
    if not native_session_id:
        return None
    from sqlmodel import Session as SqlSession
    from sqlmodel import select

    try:
        with SqlSession(_create_sync_engine()) as session:
            statement = (
                select(db_models.Session)
                .where(db_models.Session.native_session_id == native_session_id)
                .where(db_models.Session.closed_at.is_(None))  # type: ignore[union-attr]
                .order_by(db_models.Session.created_at.desc())  # type: ignore[union-attr]
                .limit(1)
            )
            row = session.exec(statement).first()
    except Exception as exc:
        logger.debug(
            "Native session lookup skipped (db unavailable)",
            native_session_id=native_session_id,
            error=str(exc),
        )
        return None
    if not row:
        return None
    return row.session_id


def _persist_session_map(agent: str, native_session_id: str | None, session_id: str) -> None:
    """Persist session mapping keyed by agent + native session id."""
    if not native_session_id:
        return
    path = _get_session_map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    try:
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            data = _load_session_map(path)
            data[_session_map_key(agent, native_session_id)] = session_id
            _write_session_map_atomic(path, data)
            logger.debug(
                "Session map persisted",
                agent=agent,
                native_session_id=(native_session_id or ""),
                session_id=session_id,
                path=str(path),
            )
    except OSError as exc:
        logger.warning("Failed to persist session map: %s", exc)


def _resolve_hook_session_id(
    *,
    agent: str,
    event_type: str,
    native_session_id: str | None,
    headless: bool,
    mint_events: frozenset[str] = frozenset(),
) -> tuple[str | None, str | None, str | None]:
    """Resolve TeleClaude session ID from the canonical native identity map path.

    Returns `(resolved_session_id, cached_session_id, existing_session_id)` where:
    - `cached_session_id` is map lookup (`agent:native_session_id -> teleclaude_session_id`)
    - `existing_session_id` is DB lookup (`sessions.native_session_id == native_session_id`)
    """
    # Non-headless route (TMUX): primary contract is the session marker.
    if not headless:
        resolved_session_id = _get_tmux_contract_session_id()
        if not resolved_session_id:
            return None, None, None

        if native_session_id and not _is_tmux_contract_session_compatible(
            resolved_session_id, native_session_id, agent=agent
        ):
            fallback_session_id = _find_session_id_by_native(native_session_id)
            if fallback_session_id:
                logger.warning(
                    "TMUX contract session mismatch; falling back to native session lookup",
                    marker_session_id=resolved_session_id,
                    fallback_session_id=fallback_session_id,
                    native_session_id=native_session_id,
                    agent=agent,
                )
                _persist_session_map(agent, native_session_id, fallback_session_id)
                return fallback_session_id, None, resolved_session_id

            logger.error(
                "TMUX contract session mismatch and no native-session fallback",
                marker_session_id=resolved_session_id,
                native_session_id=native_session_id,
                agent=agent,
            )
            return None, None, resolved_session_id

        if resolved_session_id and native_session_id:
            _persist_session_map(agent, native_session_id, resolved_session_id)
        return resolved_session_id, None, None

    # Headless route: canonical native map/DB resolution.
    cached_session_id = _get_cached_session_id(agent, native_session_id)
    resolved_session_id = _resolve_or_refresh_session_id(cached_session_id, native_session_id, agent=agent)
    existing_session_id = None

    if not resolved_session_id and native_session_id:
        existing_session_id = _find_session_id_by_native(native_session_id)

    if not resolved_session_id and existing_session_id:
        resolved_session_id = existing_session_id

    should_mint_headless = isinstance(native_session_id, str) and bool(native_session_id) and event_type in mint_events

    if not resolved_session_id and should_mint_headless:
        resolved_session_id = str(uuid.uuid4())

    if resolved_session_id and native_session_id:
        _persist_session_map(agent, native_session_id, resolved_session_id)

    return resolved_session_id, cached_session_id, existing_session_id
