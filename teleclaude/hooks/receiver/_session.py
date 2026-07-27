"""DB engine, memory context, session mapping, and TMUX/headless session resolution."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import sqlmodel
from instrukt_ai_logging import get_logger
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session as SqlSession

from teleclaude import paths as tc_paths
from teleclaude.core import db_models
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.core.session_status import is_session_terminal
from teleclaude.memory.context import generate_context_sync
from teleclaude.session_identity import get_session_id

try:
    import fcntl
except ImportError:  # pragma: no cover - platform-dependent.
    fcntl = None

logger = get_logger("teleclaude.hooks.receiver")

_SESSION_EXPORTS = [
    "_create_sync_engine",
    "_find_session_id_by_native",
    "_get_cached_session_id",
    "_get_memory_context",
    "_get_session_map_path",
    "_get_tmux_contract_tmpdir",
    "_is_headless_route",
    "_is_tmux_contract_session_compatible",
    "_load_session_map",
    "_persist_session_map",
    "prune_session_map",
    "_resolve_hook_session_id",
    "_resolve_or_refresh_session_id",
    "_session_map_key",
    "_write_session_map_atomic",
    "get_outbox_session",
]

__all__ = [
    "_create_sync_engine",
    "_find_session_id_by_native",
    "_get_cached_session_id",
    "_get_memory_context",
    "_get_session_map_path",
    "_get_tmux_contract_tmpdir",
    "_is_headless_route",
    "_is_tmux_contract_session_compatible",
    "_load_session_map",
    "_persist_session_map",
    "_resolve_hook_session_id",
    "_resolve_or_refresh_session_id",
    "_session_map_key",
    "_write_session_map_atomic",
    "get_outbox_session",
    "prune_session_map",
]


_sync_engine: Engine | None = None
_outbox_engines: dict[str, Engine] = {}


def _create_sync_engine() -> Engine:
    """Return a shared main-database engine for receiver read paths."""
    global _sync_engine
    if _sync_engine is not None:
        return _sync_engine

    _sync_engine = create_sync_db_engine(tc_paths.MAIN_DB_PATH)
    return _sync_engine


def _get_outbox_engine(outbox_db_path: str | Path) -> Engine:
    """Return a cached sync engine for the dedicated outbox database."""
    normalized_path = str(Path(outbox_db_path).expanduser())
    engine = _outbox_engines.get(normalized_path)
    if engine is None:
        engine = create_sync_db_engine(normalized_path)
        _outbox_engines[normalized_path] = engine
    return engine


def get_outbox_session(outbox_db_path: str) -> SqlSession:
    """Open a sync SQLModel session bound to the dedicated outbox database."""
    return SqlSession(_get_outbox_engine(outbox_db_path))


def _get_sqlmodel_module() -> Any:
    return sys.modules.get("sqlmodel", sqlmodel)


def _get_memory_context(project_name: str, identity_key: str | None = None) -> str:
    """Fetch pre-formatted memory context from local database."""
    try:
        db_path = str(tc_paths.MAIN_DB_PATH)
        return generate_context_sync(project_name, db_path, identity_key=identity_key)
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""


def _get_session_map_path() -> Path:
    return tc_paths.SESSION_MAP_PATH


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

    try:
        with SqlSession(_create_sync_engine()) as session:
            row = session.get(db_models.Session, session_id)
    except SQLAlchemyError as exc:
        logger.debug(
            "TMUX contract DB lookup skipped (db unavailable)",
            session_id=session_id,
            native_session_id=native_session_id,
            error=str(exc),
        )
        return True
    compatible = True
    if not row:
        logger.debug(
            "TMUX contract session not found in DB",
            session_id=session_id,
            native_session_id=native_session_id,
        )
        compatible = False
    elif row.closed_at:
        logger.debug(
            "TMUX contract session rejected: closed row",
            session_id=session_id,
            native_session_id=native_session_id,
        )
        compatible = False
    elif row.native_session_id and row.native_session_id != native_session_id:
        row_agent = (row.active_agent or "").strip().lower()
        incoming_agent = (agent or "").strip().lower()
        compatible = bool(row_agent and incoming_agent and row_agent == incoming_agent)
        if compatible:
            logger.debug(
                "TMUX contract native id rollover accepted for same agent",
                session_id=session_id,
                agent=incoming_agent,
                previous_native_session_id=(row.native_session_id or ""),
                incoming_native_session_id=native_session_id,
            )
        else:
            logger.debug(
                "TMUX contract session rejected: native session id mismatch",
                session_id=session_id,
                contract_native_session_id=(row.native_session_id or ""),
                incoming_native_session_id=native_session_id,
                contract_agent=row_agent,
                incoming_agent=incoming_agent,
            )
    return compatible


def _is_headless_route() -> bool:
    """Determine route class for this hook invocation."""
    return not bool(os.getenv("TMUX"))


def _resolve_or_refresh_session_id(
    candidate_session_id: str | None,
    raw_native_session_id: str | None,
    *,
    agent: str,
) -> str | None:
    """Validate cached session id against current DB state without mutating it."""
    if not candidate_session_id or not raw_native_session_id:
        return candidate_session_id

    try:
        sqlmodel_module = _get_sqlmodel_module()
        with sqlmodel_module.Session(_create_sync_engine()) as session:
            row = cast(db_models.Session | None, session.get(db_models.Session, candidate_session_id))
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
                logger.info(
                    "Detected stale native_session_id mapping",
                    agent=agent,
                    session_id=candidate_session_id,
                    previous_native_session_id=(row.native_session_id or ""),
                    new_native_session_id=raw_native_session_id,
                )

    except SQLAlchemyError as exc:
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

    try:
        sqlmodel_module = _get_sqlmodel_module()
        with sqlmodel_module.Session(_create_sync_engine()) as session:
            statement = sqlmodel_module.select(db_models.Session)
            statement = (
                statement.where(db_models.Session.native_session_id == native_session_id)
                .where(db_models.Session.closed_at.is_(None))  # type: ignore[union-attr]
                .order_by(db_models.Session.created_at.desc())  # type: ignore[union-attr]
                .limit(1)
            )
            row = session.exec(statement).first()
    except SQLAlchemyError as exc:
        logger.debug(
            "Native session lookup skipped (db unavailable)",
            native_session_id=native_session_id,
            error=str(exc),
        )
        return None
    if not row:
        return None
    return row.session_id


def _find_live_session_id_by_native(native_session_id: str | None) -> str | None:
    """Look up the latest non-terminal session for a native session id.

    Stricter than `_find_session_id_by_native`: also rejects terminal lifecycle
    status (e.g. `closing`), not just rows with `closed_at` set.
    `terminate_session` marks a row `closing` before killing the
    tmux pane and reclaiming its identity file, so a hook that arrives during that
    window must not be attributed to it. Kept separate from
    `_find_session_id_by_native` because that helper is also used by the headless
    route and the existing TMUX-mismatch fallback, which keep their broader
    non-closed lookup semantics.
    """
    if not native_session_id:
        return None

    try:
        sqlmodel_module = _get_sqlmodel_module()
        with sqlmodel_module.Session(_create_sync_engine()) as session:
            statement = sqlmodel_module.select(db_models.Session)
            statement = (
                statement.where(db_models.Session.native_session_id == native_session_id)
                .where(db_models.Session.closed_at.is_(None))  # type: ignore[union-attr]
                .order_by(db_models.Session.created_at.desc())  # type: ignore[union-attr]
                .limit(1)
            )
            row = session.exec(statement).first()
    except SQLAlchemyError as exc:
        logger.debug(
            "Native session lookup skipped (db unavailable)",
            native_session_id=native_session_id,
            error=str(exc),
        )
        return None
    if not row:
        return None
    if is_session_terminal(lifecycle_status=row.lifecycle_status, closed_at=row.closed_at):
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
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
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


def _session_map_row_matches(row: object | None, *, agent: str, native_session_id: str) -> bool:
    """Return whether a cached session-map row still matches DB truth."""
    if row is None:
        return False
    if getattr(row, "closed_at", None):
        return False
    if (getattr(row, "lifecycle_status", None) or "active") == "closed":
        return False
    row_agent = str(getattr(row, "active_agent", "") or "").strip().lower()
    if row_agent != agent.strip().lower():
        return False
    return getattr(row, "native_session_id", None) == native_session_id


def prune_session_map() -> int:
    """Prune stale native-to-TeleClaude session mappings against DB truth."""
    path = _get_session_map_path()
    lock_path = path.with_suffix(".lock")
    try:
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            data = _load_session_map(path)
            if not data:
                return 0

            sqlmodel_module = _get_sqlmodel_module()
            kept: dict[str, str] = {}
            with sqlmodel_module.Session(_create_sync_engine()) as session:
                for key, session_id in data.items():
                    agent, separator, native_session_id = key.partition(":")
                    if not separator or not agent or not native_session_id:
                        continue
                    row = session.get(db_models.Session, session_id)
                    if _session_map_row_matches(row, agent=agent, native_session_id=native_session_id):
                        kept[key] = session_id

            removed = len(data) - len(kept)
            if removed:
                _write_session_map_atomic(path, kept)
                logger.info("Pruned %d stale session-map entries", removed)
            return removed
    except OSError as exc:
        logger.warning("Failed to prune session map: %s", exc)
        return 0
    except SQLAlchemyError as exc:
        logger.debug("Session map pruning skipped (db unavailable): %s", exc)
        return 0


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
        # A missing TMPDIR/TMP/TEMP env is a genuine contract breach, distinct
        # from a marker that resolves to nothing (checked next). This still raises.
        _get_tmux_contract_tmpdir()
        resolved_session_id = get_session_id()
        if not resolved_session_id:
            # The marker is absent or lacks session_id. This is expected during a
            # session teardown race: `terminate_session` reclaims the per-session
            # TMPDIR (deleting the identity file) while the killed pane's agent can
            # still emit one last hook. Fall back to native-session resolution and
            # attribute the hook to a genuinely live session; when none matches
            # (including a session still `closing`), drop the event quietly rather
            # than treating it as a contract violation.
            fallback_session_id = _find_live_session_id_by_native(native_session_id)
            if fallback_session_id:
                _persist_session_map(agent, native_session_id, fallback_session_id)
                return fallback_session_id, None, None
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


_EXPORTED_SESSION_BINDINGS = (_get_memory_context, _is_headless_route, _resolve_hook_session_id)
