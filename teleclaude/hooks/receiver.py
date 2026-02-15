#!/usr/bin/env python3
"""Unified hook receiver for agent CLIs."""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

# Bootstrap: agent CLIs call this hook from arbitrary directories where PATH may
# resolve python3 to system Python (missing project deps). Re-exec under the
# project venv when needed.
_VENV_PYTHON = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python3"
if _VENV_PYTHON.is_file() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), *sys.argv])

from instrukt_ai_logging import configure_logging, get_logger  # noqa: E402

# Ensure local hooks utils and TeleClaude package are importable
hooks_dir = Path(__file__).parent
sys.path.append(str(hooks_dir))
sys.path.append(str(hooks_dir.parent.parent))

from teleclaude.config import config  # noqa: E402
from teleclaude.core.agents import AgentName  # noqa: E402
from teleclaude.core import db_models  # noqa: E402
from teleclaude.core.events import AgentHookEvents, AgentHookEventType  # noqa: E402
from teleclaude.hooks.adapters import get_adapter  # noqa: E402
from teleclaude.constants import MAIN_MODULE, UI_MESSAGE_MAX_CHARS  # noqa: E402
from teleclaude.hooks.checkpoint_flags import (  # noqa: E402
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
    set_checkpoint_flag,
)

# Bootstrap: agent CLIs call this hook from arbitrary directories where PATH may
# resolve python3 to system Python (missing project deps). Re-exec under the
# project venv when needed.
_VENV_PYTHON = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python3"
if _VENV_PYTHON.is_file() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), *sys.argv])

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Only these events are forwarded to MCP. All others are silently dropped.
# This prevents zombie mcp-wrapper processes from intermediate hooks.
# Only events with actual handlers in the daemon - infrastructure events are dropped.
_HANDLED_EVENTS: frozenset[AgentHookEventType] = AgentHookEvents.RECEIVER_HANDLED


def _create_sync_engine() -> object:
    """Create a sync SQLAlchemy engine with SQLite PRAGMAs set at connect time."""
    from sqlalchemy import create_engine
    from sqlalchemy import event as sa_event

    engine = create_engine(f"sqlite:///{config.database.path}")

    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")  # noqa: S608
        cursor.execute("PRAGMA busy_timeout = 5000")  # noqa: S608
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


def _reset_checkpoint_flags(session_id: str) -> None:
    # Keep CLEAR persistent across turns; only reset one-shot recheck limiter.
    consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)


def _maybe_checkpoint_output(
    session_id: str,
    agent: str,
    raw_data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
) -> str | None:
    """Evaluate whether to block an agent_stop with a checkpoint instruction.

    Returns the checkpoint reason string if a checkpoint is warranted, or None
    to let the stop pass through to the normal enqueue path. The caller is
    responsible for formatting the reason into agent-specific JSON via the adapter.
    """
    # Session-scoped persistent disable: while clear marker exists, skip checkpoints.
    if is_checkpoint_disabled(session_id):
        consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)
        logger.info("Checkpoint skipped (persistent clear flag)", session_id=session_id[:8], agent=agent)
        return None

    stop_hook_active = bool(raw_data.get("stop_hook_active"))
    if stop_hook_active and consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG):
        logger.info("Checkpoint skipped (recheck limit reached)", session_id=session_id[:8], agent=agent)
        return None

    from sqlmodel import Session as SqlSession

    try:
        with SqlSession(_create_sync_engine()) as db_session:
            row = db_session.get(db_models.Session, session_id)
    except Exception as exc:  # noqa: BLE001 - fail-open: let stop through on DB errors
        logger.debug("Checkpoint eval skipped (db error)", error=str(exc))
        return None

    if not row:
        return None

    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    checkpoint_at = _as_utc(row.last_checkpoint_at)
    message_at = _as_utc(row.last_message_sent_at)
    now = datetime.now(timezone.utc)

    # Turn start = most recent input event (real user message or previous checkpoint)
    turn_candidates = [dt for dt in (message_at, checkpoint_at) if dt is not None]
    turn_start = max(turn_candidates, default=None)
    if not turn_start:
        logger.debug("Checkpoint skipped (no turn start) for session %s", session_id[:8])
        return None

    elapsed = (now - turn_start).total_seconds()

    # Capture session fields before the DB update re-fetches row
    transcript_path = getattr(row, "native_log_file", None)
    working_slug = getattr(row, "working_slug", None)

    logger.debug("Checkpoint eval for session %s (%.1fs elapsed)", session_id[:8], elapsed)

    # Build context-aware checkpoint message from git diff + transcript
    from teleclaude.hooks.checkpoint import get_checkpoint_content

    # Prefer persisted session project_path (source of truth). Fall back to
    # transcript-derived workdir only when project_path is missing.
    project_path = str(getattr(row, "project_path", "") or "")
    if not project_path and transcript_path:
        from teleclaude.utils.transcript import extract_workdir_from_transcript

        project_path = extract_workdir_from_transcript(transcript_path) or ""
    try:
        agent_enum = AgentName.from_str(agent)
    except ValueError:
        agent_enum = AgentName.CLAUDE
    checkpoint_reason = get_checkpoint_content(
        transcript_path=transcript_path,
        agent_name=agent_enum,
        project_path=project_path,
        working_slug=working_slug,
        elapsed_since_turn_start_s=elapsed,
    )
    if not checkpoint_reason:
        logger.debug(
            "Checkpoint skipped: no turn-local changes for session %s (transcript=%s)",
            session_id[:8],
            transcript_path or "<none>",
        )
        return None

    # Claude stop_hook_active indicates we already blocked once for this turn.
    # If no explicit clear marker is provided, allow at most one extra recheck.
    if stop_hook_active:
        set_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)

    # Checkpoint warranted — update DB and return agent-specific blocking JSON
    try:
        with SqlSession(_create_sync_engine()) as db_session:
            update_row = db_session.get(db_models.Session, session_id)
            if update_row:
                update_row.last_checkpoint_at = now
                db_session.add(update_row)
                db_session.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort DB update
        logger.warning("Checkpoint DB update failed: %s", exc)
    logger.info(
        "Checkpoint payload prepared",
        route="hook",
        session=session_id[:8],
        agent=agent,
        transcript_present=bool(transcript_path),
        project_path=project_path or "",
        working_slug=working_slug or "",
        payload_len=len(checkpoint_reason),
    )

    return checkpoint_reason


def _print_memory_injection(cwd: str | None, adapter: object, session_id: str | None = None) -> None:
    """Print memory context to stdout for agent context injection via SessionStart hook."""
    project_name = Path(cwd).name if cwd else None
    if not project_name:
        return

    # Resolve identity_key from session adapter metadata for identity-scoped memories
    identity_key: str | None = None
    if session_id:
        try:
            from teleclaude.core.identity import derive_identity_key
            from teleclaude.core.models import SessionAdapterMetadata
            from sqlmodel import Session as SqlSession

            with SqlSession(_create_sync_engine()) as db_session:
                row = db_session.get(db_models.Session, session_id)
                if row and row.adapter_metadata:
                    adapter_meta = SessionAdapterMetadata.from_json(row.adapter_metadata)
                    identity_key = derive_identity_key(adapter_meta)
        except Exception:  # noqa: BLE001 - fail-open: identity resolution is best-effort
            logger.debug("Identity key derivation failed for session %s", (session_id or "")[:8])

    context = _get_memory_context(project_name, identity_key=identity_key)
    if not context:
        return

    logger.debug("Memory context fetched", project=project_name, length=len(context), identity_key=identity_key or "")
    payload = adapter.format_memory_injection(context)  # type: ignore[union-attr]
    if payload:
        print(payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TeleClaude hook receiver")
    parser.add_argument(
        "--agent",
        required=True,
        choices=AgentName.choices(),
        help="Agent name for adapter selection",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Caller working directory for headless session attribution",
    )
    parser.add_argument("event_type", nargs="?", default=None, help="Hook event type")
    return parser.parse_args()


# guard: loose-dict-func - Raw stdin JSON payload at process boundary.
def _read_stdin() -> tuple[str, dict[str, object]]:
    raw_input = ""
    data: dict[str, object] = {}
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read()
        if raw_input.strip():
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object")
            data = cast(dict[str, object], parsed)
    return raw_input, data


def _log_raw_input(raw_input: str, *, log_raw: bool) -> None:
    if not raw_input:
        return
    truncated = len(raw_input) > UI_MESSAGE_MAX_CHARS
    if log_raw:
        logger.trace(
            "receiver raw input",
            raw=raw_input[:UI_MESSAGE_MAX_CHARS],
            raw_len=len(raw_input),
            truncated=truncated,
        )
    else:
        logger.trace(
            "receiver raw input",
            raw_len=len(raw_input),
            truncated=truncated,
        )


def _enqueue_hook_event(
    session_id: str,
    event_type: str,
    data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON.
) -> None:
    """Persist hook event to local outbox for durable delivery."""
    now = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(data)
    from sqlmodel import Session as SqlSession

    with SqlSession(_create_sync_engine()) as session:
        row = db_models.HookOutbox(
            session_id=session_id,
            event_type=event_type,
            payload=payload_json,
            created_at=now,
            next_attempt_at=now,
            attempt_count=0,
        )
        session.add(row)
        session.commit()


def _update_session_native_fields(
    session_id: str,
    *,
    agent: str,
    event_type: str,
    native_log_file: str | None = None,
    native_session_id: str | None = None,
) -> None:
    """Update native session fields directly on the session row."""
    if not native_log_file and not native_session_id:
        return
    from sqlmodel import Session as SqlSession

    with SqlSession(_create_sync_engine()) as session:
        row = session.get(db_models.Session, session_id)
        if not row:
            return
        previous_native_session_id = row.native_session_id
        previous_native_log_file = row.native_log_file
        if native_log_file:
            row.native_log_file = native_log_file
        if native_session_id:
            row.native_session_id = native_session_id
        session.add(row)
        session.commit()

        session_changed = bool(native_session_id and previous_native_session_id != native_session_id)
        transcript_changed = bool(native_log_file and previous_native_log_file != native_log_file)
        if not session_changed and not transcript_changed:
            return

        old_path = Path(previous_native_log_file).expanduser() if previous_native_log_file else None
        new_path = Path(native_log_file).expanduser() if native_log_file else None
        old_exists = bool(old_path and old_path.exists())
        new_exists = bool(new_path and new_path.exists())

        logger.info(
            "Native session metadata changed",
            session_id=session_id[:8],
            agent=agent,
            event_type=event_type,
            native_session_id_before=(previous_native_session_id or "")[:8],
            native_session_id_after=(native_session_id or "")[:8],
            native_session_changed=session_changed,
            native_log_file_before=previous_native_log_file or "",
            native_log_file_after=native_log_file or "",
            native_log_changed=transcript_changed,
            old_path_exists=old_exists,
            new_path_exists=new_exists,
        )


def _get_session_map_path() -> Path:
    return Path(os.path.expanduser("~/.teleclaude/session_map.json"))


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
        native_session_id=(native_session_id or "")[:8],
        cached_session_id=(cached or "")[:8],
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
    except Exception as exc:  # noqa: BLE001 - fail-open when DB access is unavailable.
        logger.debug(
            "TMUX contract DB lookup skipped (db unavailable)",
            session_id=session_id[:8],
            native_session_id=native_session_id[:8],
            error=str(exc),
        )
        return True

    if not row:
        logger.debug(
            "TMUX contract session not found in DB",
            session_id=session_id[:8],
            native_session_id=native_session_id[:8],
        )
        return False

    if row.closed_at:
        logger.debug(
            "TMUX contract session rejected: closed row",
            session_id=session_id[:8],
            native_session_id=native_session_id[:8],
        )
        return False

    if row.native_session_id and row.native_session_id != native_session_id:
        row_agent = (row.active_agent or "").strip().lower()
        incoming_agent = (agent or "").strip().lower()
        if row_agent and incoming_agent and row_agent == incoming_agent:
            logger.debug(
                "TMUX contract native id rollover accepted for same agent",
                session_id=session_id[:8],
                agent=incoming_agent,
                previous_native_session_id=(row.native_session_id or "")[:8],
                incoming_native_session_id=native_session_id[:8],
            )
            return True
        logger.debug(
            "TMUX contract session rejected: native session id mismatch",
            session_id=session_id[:8],
            contract_native_session_id=(row.native_session_id or "")[:8],
            incoming_native_session_id=native_session_id[:8],
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
    """Validate cached session id against current DB state for headless routing."""
    if not candidate_session_id or not raw_native_session_id:
        return candidate_session_id

    from sqlmodel import Session as SqlSession

    try:
        with SqlSession(_create_sync_engine()) as session:
            row = session.get(db_models.Session, candidate_session_id)
    except Exception as exc:  # noqa: BLE001 - fail-open to preserve hook delivery on partial DB fixtures
        logger.debug(
            "Session refresh lookup skipped (db unavailable)",
            agent=agent,
            session_id=candidate_session_id[:8],
            error=str(exc),
        )
        return candidate_session_id
    if not row:
        logger.debug(
            "Invalidating cached session mapping: session row not found",
            agent=agent,
            session_id=candidate_session_id[:8],
            native_session_id=raw_native_session_id[:8],
        )
        return None

    if row.closed_at:
        logger.debug(
            "Invalidating cached session mapping: session closed",
            agent=agent,
            session_id=candidate_session_id[:8],
            native_session_id=raw_native_session_id[:8],
        )
        return None
    if row.lifecycle_status != "headless":
        logger.debug(
            "Invalidating cached session mapping: non-headless lifecycle",
            agent=agent,
            session_id=candidate_session_id[:8],
            native_session_id=raw_native_session_id[:8],
            lifecycle_status=row.lifecycle_status,
        )
        return None

    if row.native_session_id and row.native_session_id != raw_native_session_id:
        logger.debug(
            "Invalidating cached session mapping: native session mismatch",
            agent=agent,
            session_id=candidate_session_id[:8],
            cached_native_session_id=(row.native_session_id or "")[:8],
            incoming_native_session_id=raw_native_session_id[:8],
        )
        return None

    return candidate_session_id


def _find_session_id_by_native(native_session_id: str | None) -> str | None:
    """Look up the latest non-closed session for a native session id."""
    if not native_session_id:
        return None
    from sqlmodel import Session as SqlSession, select

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
    except Exception as exc:  # noqa: BLE001 - fail-open in test fixtures / partial DB states
        logger.debug(
            "Native session lookup skipped (db unavailable)",
            native_session_id=native_session_id[:8],
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
                native_session_id=(native_session_id or "")[:8],
                session_id=session_id[:8],
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
                    marker_session_id=resolved_session_id[:8],
                    fallback_session_id=fallback_session_id[:8],
                    native_session_id=native_session_id[:8],
                    agent=agent,
                )
                _persist_session_map(agent, native_session_id, fallback_session_id)
                return fallback_session_id, None, resolved_session_id

            logger.error(
                "TMUX contract session mismatch and no native-session fallback",
                marker_session_id=resolved_session_id[:8],
                native_session_id=native_session_id[:8],
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


def _emit_receiver_error_best_effort(
    *,
    agent: str,
    event_type: str | None,
    message: str,
    code: str,
    details: dict[str, object] | None = None,  # guard: loose-dict - Error details are context-specific.
    raw_data: dict[str, object] | None = None,  # guard: loose-dict - Raw hook payload for best-effort context.
) -> None:
    """Best-effort error emission for receiver contract violations."""
    payload = dict(details or {})
    payload.update(
        {
            "agent": agent,
            "event_type": event_type,
            "code": code,
        }
    )

    try:
        raw_native_session_id = None
        if raw_data is not None:
            # Try canonical name first, then Codex raw name as fallback
            raw_id = raw_data.get("session_id") or raw_data.get("thread-id")
            if isinstance(raw_id, str):
                raw_native_session_id = raw_id
        session_id = _get_cached_session_id(agent, raw_native_session_id)
        if not session_id:
            session_id = _find_session_id_by_native(raw_native_session_id)
        if not session_id:
            logger.error(
                "Receiver error with unknown session",
                agent=agent,
                event_type=event_type,
                code=code,
                message=message,
            )
            return
        _enqueue_hook_event(
            session_id,
            "error",
            {
                "message": message,
                "source": "hook_receiver",
                "code": code,
                "details": payload,
                "severity": "error",
                "retryable": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 - never crash receiver on best-effort error path
        logger.error("Receiver error reporting failed", error=str(exc), code=code)


# guard: loose-dict-func - Main path processes raw hook payload boundaries.
def main() -> None:
    args = _parse_args()

    logger.trace(
        "Hook receiver start",
        argv=sys.argv,
        cwd=os.getcwd(),
        stdin_tty=sys.stdin.isatty(),
        has_event_arg=bool(args.event_type),
        agent=args.agent,
    )

    adapter = get_adapter(args.agent)

    # Parse input via adapter (agent-specific input format)
    try:
        raw_input, raw_event_type, raw_data = adapter.parse_input(args)
    except json.JSONDecodeError:
        _emit_receiver_error_best_effort(
            agent=args.agent,
            event_type=getattr(args, "event_type", None),
            message="Invalid hook payload JSON",
            code="HOOK_INVALID_JSON",
        )
        sys.exit(1)
    except ValueError as exc:
        _emit_receiver_error_best_effort(
            agent=args.agent,
            event_type=getattr(args, "event_type", None),
            message=str(exc),
            code="HOOK_PAYLOAD_NOT_OBJECT",
        )
        sys.exit(1)

    # log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    log_raw = True
    _log_raw_input(raw_input, log_raw=log_raw)

    # Map agent-specific event_type to TeleClaude internal event_type
    event_type = raw_event_type
    agent_map = AgentHookEvents.HOOK_EVENT_MAP.get(args.agent, {})

    # Contract boundary: event names are trusted; only exact mapping is allowed.
    mapped_event_type = agent_map.get(raw_event_type)

    # Use mapped event if found, otherwise keep original (for direct events like 'tool_done')
    if mapped_event_type:
        event_type = mapped_event_type
        logger.debug("Mapped hook event: %s -> %s", raw_event_type, event_type)

    # Event types outside the handled contract are ignored by design.
    if event_type not in _HANDLED_EVENTS:
        logger.debug(
            "Dropped unhandled hook event", event_type=event_type, raw_event_type=raw_event_type, agent=args.agent
        )
        sys.exit(0)

    headless_route = _is_headless_route()

    # Normalize payload: maps agent-specific field names to canonical internal names.
    # After this, all agents use: session_id, transcript_path, prompt, message.
    data = adapter.normalize_payload(dict(raw_data))

    # Extract native identity from normalized data (agent-agnostic)
    raw_native_session_id: str | None = None
    raw_id = data.get("session_id")
    if isinstance(raw_id, str):
        raw_native_session_id = raw_id

    raw_native_log_file: str | None = None
    raw_log = data.get("transcript_path")
    if isinstance(raw_log, str):
        raw_native_log_file = raw_log

    try:
        teleclaude_session_id, cached_session_id, existing_id = _resolve_hook_session_id(
            agent=args.agent,
            event_type=event_type,
            native_session_id=raw_native_session_id,
            headless=headless_route,
            mint_events=adapter.mint_events,
        )
    except ValueError as exc:
        logger.error(
            "Hook receiver contract violation",
            agent=args.agent,
            event_type=event_type,
            headless=headless_route,
            error=str(exc),
        )
        sys.exit(1)
    logger.debug(
        "Hook session resolution",
        agent=args.agent,
        headless=headless_route,
        event_type=event_type,
        cached_session_id=(cached_session_id or "")[:8],
        existing_session_id=(existing_id or "")[:8],
        resolved_session_id=(teleclaude_session_id or "")[:8],
        native_session_id=(raw_native_session_id or "")[:8],
    )
    if not teleclaude_session_id:
        logger.error(
            "Hook session resolution failed (contract violation)",
            agent=args.agent,
            headless=headless_route,
            event_type=event_type,
            raw_event_type=raw_event_type,
            native_session_id=(raw_native_session_id or "")[:8],
            cached_session_id=(cached_session_id or "")[:8],
            existing_session_id=(existing_id or "")[:8],
        )
        sys.exit(1)

    logger.debug(
        "Hook event received",
        event_type=event_type,
        session_id=teleclaude_session_id,
        agent=args.agent,
    )

    logger.debug(
        "Hook payload summary",
        event_type=event_type,
        agent=args.agent,
        session_id=teleclaude_session_id,
        raw_native_session_id=raw_native_session_id,
        raw_transcript_path=raw_native_log_file,
    )

    # Preserve native_session_id if present (needed for later tooling lookups)
    if raw_native_session_id:
        data["native_session_id"] = raw_native_session_id
    if raw_native_log_file:
        data["native_log_file"] = raw_native_log_file

    if raw_native_session_id or raw_native_log_file:
        try:
            _update_session_native_fields(
                teleclaude_session_id,
                agent=args.agent,
                event_type=event_type,
                native_log_file=raw_native_log_file,
                native_session_id=raw_native_session_id,
            )
        except Exception as exc:  # Best-effort update; never fail hook.
            logger.warning(
                "Hook metadata update failed (ignored)",
                event_type=event_type,
                session_id=teleclaude_session_id,
                agent=args.agent,
                error=str(exc),
            )

    cwd = getattr(args, "cwd", None)
    if isinstance(cwd, str) and cwd:
        data["cwd"] = cwd

    # Guard: Some Gemini BeforeAgent hooks arrive with an empty prompt.
    # These are not real user turns and must not overwrite last_message_sent.
    if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
        prompt_value = data.get("prompt")
        prompt_text = prompt_value if isinstance(prompt_value, str) else ""
        if not prompt_text.strip():
            logger.warning(
                "Dropped empty user_prompt_submit hook event",
                agent=args.agent,
                session_id=teleclaude_session_id[:8],
                native_session_id=(raw_native_session_id or "")[:8],
                hook_event_name=str(data.get("hook_event_name") or ""),
                raw_event_type=str(raw_event_type or ""),
            )
            return
        _reset_checkpoint_flags(teleclaude_session_id)

    # Inject memory index into STDOUT for SessionStart (Agent Context)
    if event_type == AgentHookEvents.AGENT_SESSION_START:
        cwd = args.cwd
        if cwd:
            project_name = Path(cwd).name
            logger.debug("Injecting memory index for session_start", project=project_name)
            _print_memory_injection(cwd, adapter, session_id=teleclaude_session_id)
        else:
            logger.error("Skipping memory injection: no CWD provided (contract violation)")

    # Hook-based checkpoint: skip for agents that don't support hook blocking.
    # If checkpoint fires: print blocking JSON, exit 0, skip enqueue (agent continues).
    # If no checkpoint: fall through to enqueue (real stop enters the system).
    if event_type == AgentHookEvents.AGENT_STOP and adapter.supports_hook_checkpoint:
        checkpoint_reason: str | None = None
        try:
            checkpoint_reason = _maybe_checkpoint_output(teleclaude_session_id, args.agent, raw_data)
        except Exception as exc:  # noqa: BLE001 - fail-open: never break hooks on checkpoint logic
            logger.warning(
                "Checkpoint eval crashed (ignored)",
                event_type=event_type,
                session_id=teleclaude_session_id[:8],
                agent=args.agent,
                error=str(exc),
            )
        if checkpoint_reason:
            checkpoint_json = adapter.format_checkpoint_response(checkpoint_reason)
            if checkpoint_json:
                print(checkpoint_json)
                sys.exit(0)

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(timezone.utc).isoformat()

    _enqueue_hook_event(teleclaude_session_id, event_type, data)


if __name__ == MAIN_MODULE:
    main()
