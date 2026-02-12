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

from instrukt_ai_logging import configure_logging, get_logger

# Ensure local hooks utils and TeleClaude package are importable
hooks_dir = Path(__file__).parent
sys.path.append(str(hooks_dir))
sys.path.append(str(hooks_dir.parent.parent))

from teleclaude.config import config  # noqa: E402
from teleclaude.core.agents import AgentName  # noqa: E402
from teleclaude.core import db_models  # noqa: E402
from teleclaude.core.events import AgentHookEvents, AgentHookEventType  # noqa: E402
from teleclaude.constants import MAIN_MODULE, UI_MESSAGE_MAX_CHARS  # noqa: E402
from teleclaude.hooks.checkpoint_flags import (  # noqa: E402
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
    set_checkpoint_flag,
)

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Only these events are forwarded to MCP. All others are silently dropped.
# This prevents zombie mcp-wrapper processes from intermediate hooks.
# Only events with actual handlers in the daemon - infrastructure events are dropped.
_HANDLED_EVENTS: frozenset[AgentHookEventType] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
        AgentHookEvents.TOOL_DONE,
        AgentHookEvents.TOOL_USE,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_NOTIFICATION,
        AgentHookEvents.AGENT_ERROR,
    }
)


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


def _get_memory_context(project_name: str) -> str:
    """Fetch pre-formatted memory context from local database."""
    try:
        from teleclaude.memory.context import generate_context_sync

        db_path = str(config.database.path)
        return generate_context_sync(project_name, db_path)
    except Exception:
        return ""


def _format_injection_payload(agent: str, context: str) -> str:
    """Format context into agent-specific SessionStart hook response JSON."""
    if agent == AgentName.CLAUDE.value:
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    if agent == AgentName.GEMINI.value:
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "additionalContext": context,
                }
            }
        )
    # Codex has no SessionStart hook mechanism
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

    Returns agent-specific JSON to print to stdout (blocking the stop), or None
    to let the stop pass through to the normal enqueue path.
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

    # Codex does not support hook blocking; checkpoint injection is handled
    # by AgentCoordinator tmux logic only.
    if agent == AgentName.CODEX.value:
        logger.debug("Checkpoint skipped (codex uses tmux injection path)")
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

    if agent == AgentName.CLAUDE.value:
        return json.dumps({"decision": "block", "reason": checkpoint_reason})
    if agent == AgentName.GEMINI.value:
        return json.dumps({"decision": "deny", "reason": checkpoint_reason})

    # Codex has no hook-based checkpoint mechanism
    return None


def _print_memory_injection(cwd: str | None, agent: str) -> None:
    """Print memory context to stdout for agent context injection via SessionStart hook."""
    project_name = Path(cwd).name if cwd else None
    if not project_name:
        return

    context = _get_memory_context(project_name)
    if not context:
        return

    logger.debug("Memory context fetched", project=project_name, length=len(context))
    print(_format_injection_payload(agent, context))


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


# guard: loose-dict-func - Native identity fields come from dynamic hook payloads.
def _extract_native_identity(agent: str, data: dict[str, object]) -> tuple[str | None, str | None]:
    """Extract native session id + transcript path from raw hook payload."""
    native_session_id: str | None = None
    native_log_file: str | None = None

    if agent == AgentName.CODEX.value:
        raw_id = data.get("thread-id")
    else:
        raw_id = data.get("session_id")
    if isinstance(raw_id, str):
        native_session_id = raw_id

    raw_log = data.get("transcript_path")
    if isinstance(raw_log, str):
        native_log_file = raw_log

    # Codex payloads lack transcript_path; discover from filesystem.
    if not native_log_file and agent == AgentName.CODEX.value and native_session_id:
        from teleclaude.hooks.adapters.codex import _discover_transcript_path

        discovered = _discover_transcript_path(native_session_id)
        if discovered:
            native_log_file = discovered

    return native_session_id, native_log_file


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


def _get_env_session_id() -> str | None:
    """Read TeleClaude session ID from process environment context."""
    direct = os.getenv("TELECLAUDE_SESSION_ID")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    tmpdir = os.getenv("TMPDIR")
    if not isinstance(tmpdir, str) or not tmpdir.strip():
        return None
    marker = Path(tmpdir).expanduser() / "teleclaude_session_id"
    try:
        value = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _is_active_session(session_id: str | None) -> bool:
    """Return True when session_id exists in DB and is not closed."""
    if not session_id:
        return False
    from sqlmodel import Session as SqlSession

    try:
        with SqlSession(_create_sync_engine()) as session:
            row = session.get(db_models.Session, session_id)
    except Exception:
        return False
    return bool(row and not row.closed_at)


def _resolve_or_refresh_session_id(
    candidate_session_id: str | None,
    raw_native_session_id: str | None,
    *,
    agent: str,
) -> str | None:
    """Ensure a native session maps to the correct TeleClaude session id.

    If the cached teleclaude_session_id points at a different native session,
    mint a new TeleClaude session id and persist it for subsequent hooks.
    """
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
        return candidate_session_id

    if row.closed_at:
        new_session_id = str(uuid.uuid4())
        _persist_session_map(agent, raw_native_session_id, new_session_id)
        return new_session_id
    if row.lifecycle_status != "headless":
        return candidate_session_id

    if row.native_session_id and row.native_session_id != raw_native_session_id:
        new_session_id = str(uuid.uuid4())
        _persist_session_map(agent, raw_native_session_id, new_session_id)
        return new_session_id

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
) -> tuple[str | None, str | None, str | None]:
    """Resolve TeleClaude session ID from the canonical native identity map path.

    Returns `(resolved_session_id, cached_session_id, existing_session_id)` where:
    - `cached_session_id` is map lookup (`agent:native_session_id -> teleclaude_session_id`)
    - `existing_session_id` is DB lookup (`sessions.native_session_id == native_session_id`)
    """
    cached_session_id = _get_cached_session_id(agent, native_session_id)
    resolved_session_id = _resolve_or_refresh_session_id(cached_session_id, native_session_id, agent=agent)
    existing_session_id = None
    env_session_id = _get_env_session_id()

    # For session_start, prefer the explicit TeleClaude session context from TMPDIR/env.
    # This binds agent-native IDs to the already-created interactive session instead of minting
    # a second headless session when map/native lookup is not yet populated.
    if (
        event_type == AgentHookEvents.AGENT_SESSION_START
        and env_session_id
        and _is_active_session(env_session_id)
        and resolved_session_id != env_session_id
    ):
        resolved_session_id = env_session_id

    if not resolved_session_id and native_session_id:
        existing_session_id = _find_session_id_by_native(native_session_id)

    if not resolved_session_id and existing_session_id:
        resolved_session_id = existing_session_id

    if (
        not resolved_session_id
        and event_type == AgentHookEvents.AGENT_SESSION_START
        and isinstance(native_session_id, str)
        and native_session_id
    ):
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
            raw_native_session_id, _ = _extract_native_identity(agent, raw_data)
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

    # Read input based on agent type
    if args.agent == AgentName.CODEX.value:
        # Codex notify passes JSON as command-line argument, event is always "agent_stop"
        raw_input = args.event_type or ""
        try:
            parsed = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            _emit_receiver_error_best_effort(
                agent=args.agent,
                event_type="agent_stop",
                message="Invalid hook payload JSON from codex notify argument",
                code="HOOK_INVALID_JSON",
                details={"raw_payload_present": bool(raw_input.strip())},
            )
            sys.exit(1)
        if not isinstance(parsed, dict):
            _emit_receiver_error_best_effort(
                agent=args.agent,
                event_type="agent_stop",
                message="Codex hook payload must be a JSON object",
                code="HOOK_PAYLOAD_NOT_OBJECT",
            )
            sys.exit(1)
        raw_data = cast(dict[str, object], parsed)
        event_type = "agent_stop"
    else:
        # Claude/Gemini pass event_type as arg, JSON on stdin
        event_type = cast(str, args.event_type)
        try:
            raw_input, raw_data = _read_stdin()
        except json.JSONDecodeError:
            _emit_receiver_error_best_effort(
                agent=args.agent,
                event_type=event_type,
                message="Invalid hook payload JSON from stdin",
                code="HOOK_INVALID_JSON",
            )
            sys.exit(1)
        except ValueError as exc:
            _emit_receiver_error_best_effort(
                agent=args.agent,
                event_type=event_type,
                message=str(exc),
                code="HOOK_PAYLOAD_NOT_OBJECT",
            )
            sys.exit(1)

    # log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    log_raw = True
    _log_raw_input(raw_input, log_raw=log_raw)

    # Map agent-specific event_type to TeleClaude internal event_type
    raw_event_type = event_type
    agent_map = AgentHookEvents.HOOK_EVENT_MAP.get(args.agent, {})

    # Try direct match, then try title-cased match (e.g., 'tool_use' -> 'ToolUse')
    # Use replace('_', '') to handle snake_case to PascalCase mapping if needed.
    pascal_event_type = raw_event_type.replace("_", " ").title().replace(" ", "") if raw_event_type else None

    mapped_event_type = agent_map.get(raw_event_type) or agent_map.get(pascal_event_type)

    # Use mapped event if found, otherwise keep original (for direct events like 'tool_done')
    if mapped_event_type:
        event_type = mapped_event_type
        logger.debug("Mapped hook event: %s (pascal: %s) -> %s", raw_event_type, pascal_event_type, event_type)

    # Early exit for unhandled events - don't spawn mcp-wrapper
    # Note: We check against AgentHookEvents.ALL which contains internal types like TOOL_DONE
    if event_type not in _HANDLED_EVENTS:
        if event_type in {"prompt", "stop"}:
            _emit_receiver_error_best_effort(
                agent=args.agent,
                event_type=event_type,
                message="Deprecated hook event type; expected user_prompt_submit or agent_stop",
                code="HOOK_EVENT_DEPRECATED",
                raw_data=raw_data,
            )
            sys.exit(1)
        logger.error("Unhandled hook event: %s (raw: %s)", event_type, raw_event_type)
        sys.exit(1)

    raw_native_session_id, raw_native_log_file = _extract_native_identity(args.agent, raw_data)

    teleclaude_session_id, cached_session_id, existing_id = _resolve_hook_session_id(
        agent=args.agent,
        event_type=event_type,
        native_session_id=raw_native_session_id,
    )
    logger.debug(
        "Hook session resolution",
        agent=args.agent,
        event_type=event_type,
        cached_session_id=(cached_session_id or "")[:8],
        existing_session_id=(existing_id or "")[:8],
        resolved_session_id=(teleclaude_session_id or "")[:8],
        native_session_id=(raw_native_session_id or "")[:8],
    )
    if not teleclaude_session_id:
        # Registration is only allowed on session_start. Other events require an existing mapping.
        sys.exit(0)

    data = dict(raw_data)

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
            _print_memory_injection(cwd, args.agent)
        else:
            logger.error("Skipping memory injection: no CWD provided (contract violation)")

    # Hook-based invisible checkpoint for Claude/Gemini.
    # If checkpoint fires: print blocking JSON, exit 0, skip enqueue (agent continues).
    # If no checkpoint: fall through to enqueue (real stop enters the system).
    if event_type == AgentHookEvents.AGENT_STOP:
        checkpoint_json: str | None = None
        try:
            checkpoint_json = _maybe_checkpoint_output(teleclaude_session_id, args.agent, raw_data)
        except Exception as exc:  # noqa: BLE001 - fail-open: never break hooks on checkpoint logic
            logger.warning(
                "Checkpoint eval crashed (ignored)",
                event_type=event_type,
                session_id=teleclaude_session_id[:8],
                agent=args.agent,
                error=str(exc),
            )
        if checkpoint_json:
            print(checkpoint_json)
            sys.exit(0)

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(timezone.utc).isoformat()

    _enqueue_hook_event(teleclaude_session_id, event_type, data)


if __name__ == MAIN_MODULE:
    main()
