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
from typing import Any, Mapping, Protocol, cast

from instrukt_ai_logging import configure_logging, get_logger

# Ensure local hooks utils and TeleClaude package are importable
hooks_dir = Path(__file__).parent
sys.path.append(str(hooks_dir))
sys.path.append(str(hooks_dir.parent.parent))

from adapters import claude as claude_adapter  # noqa: E402
from adapters import codex as codex_adapter  # noqa: E402
from adapters import gemini as gemini_adapter  # noqa: E402


from teleclaude.config import config  # noqa: E402
from teleclaude.core.agents import AgentName  # noqa: E402
from teleclaude.core import db_models  # noqa: E402
from teleclaude.constants import MAIN_MODULE, UI_MESSAGE_MAX_CHARS  # noqa: E402
from teleclaude.hooks.adapters.models import NormalizedHookPayload  # noqa: E402

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Only these events are forwarded to MCP. All others are silently dropped.
# This prevents zombie mcp-wrapper processes from intermediate hooks.
_HANDLED_EVENTS: frozenset[str] = frozenset(
    {
        "session_start",
        "prompt",
        "stop",
        "notification",
        "session_end",
        "before_agent",
        "before_model",
        "after_model",
        "before_tool_selection",
        "before_tool",
        "after_tool",
        "pre_compress",
    }
)


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


def _read_stdin() -> tuple[str, dict[str, object]]:  # guard: loose-dict - Raw stdin JSON payload.
    raw_input = ""
    data: dict[str, object] = {}  # guard: loose-dict - Raw stdin JSON payload.
    try:
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read()
            data = json.loads(raw_input) if raw_input.strip() else {}
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON from stdin")
        data = {}
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


def _send_error_event(
    session_id: str,
    message: str,
    details: Mapping[str, Any],
) -> None:
    _enqueue_hook_event(
        session_id,
        "error",
        {"message": message, "source": "hook_receiver", "details": details},
    )


def _enqueue_hook_event(
    session_id: str,
    event_type: str,
    data: Mapping[str, Any],
) -> None:
    """Persist hook event to local outbox for durable delivery."""
    db_path = config.database.path
    now = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(data)
    from sqlalchemy import create_engine, text
    from sqlmodel import Session as SqlSession

    engine = create_engine(f"sqlite:///{db_path}")
    with SqlSession(engine) as session:
        session.exec(text("PRAGMA journal_mode = WAL"))
        session.exec(text("PRAGMA busy_timeout = 5000"))
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


def _extract_native_identity(agent: str, data: Mapping[str, Any]) -> tuple[str | None, str | None]:
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

    return native_session_id, native_log_file


def _get_env_session_id() -> str | None:
    value = os.getenv("TELECLAUDE_SESSION_ID")
    if isinstance(value, str) and value.strip():
        return value.strip()
    # Legacy tmux session id file (compat + tests)
    tmpdir = os.getenv("TMPDIR")
    if tmpdir:
        legacy_path = Path(tmpdir) / "teleclaude_session_id"
        if legacy_path.exists():
            try:
                contents = legacy_path.read_text(encoding="utf-8").strip()
            except OSError:
                contents = ""
            if contents:
                return contents
    return None


def _get_session_map_path() -> Path | None:
    tmpdir = os.getenv("TMPDIR")
    if not tmpdir:
        return None
    return Path(tmpdir) / "teleclaude_session_map.json"


def _session_map_key(agent: str, native_session_id: str) -> str:
    return f"{agent}:{native_session_id}"


def _load_session_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    return {}


def _write_session_map_atomic(path: Path, data: dict[str, str]) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)


def _get_cached_session_id(agent: str, native_session_id: str | None) -> str | None:
    if not native_session_id:
        return None
    path = _get_session_map_path()
    if not path:
        return None
    data = _load_session_map(path)
    return data.get(_session_map_key(agent, native_session_id))


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

    db_path = config.database.path
    from sqlalchemy import create_engine, text
    from sqlmodel import Session as SqlSession

    engine = create_engine(f"sqlite:///{db_path}")
    with SqlSession(engine) as session:
        row = session.exec(
            text(
                "SELECT native_session_id, lifecycle_status, closed_at FROM sessions WHERE session_id = :session_id"
            ).bindparams(session_id=candidate_session_id)
        ).first()
    if not row:
        return candidate_session_id

    native_session_id = None
    lifecycle_status = None
    closed_at = None
    if hasattr(row, "_mapping"):
        mapping = row._mapping  # type: ignore[attr-defined]
        native_session_id = mapping.get("native_session_id")
        lifecycle_status = mapping.get("lifecycle_status")
        closed_at = mapping.get("closed_at")
    elif isinstance(row, tuple):
        native_session_id = row[0] if len(row) > 0 else None
        lifecycle_status = row[1] if len(row) > 1 else None
        closed_at = row[2] if len(row) > 2 else None
    if closed_at:
        new_session_id = str(uuid.uuid4())
        _persist_session_map(agent, raw_native_session_id, new_session_id)
        return new_session_id
    if lifecycle_status != "headless":
        return candidate_session_id

    if native_session_id and native_session_id != raw_native_session_id:
        new_session_id = str(uuid.uuid4())
        _persist_session_map(agent, raw_native_session_id, new_session_id)
        return new_session_id

    return candidate_session_id


def _persist_session_map(agent: str, native_session_id: str | None, session_id: str) -> None:
    """Persist session mapping keyed by agent + native session id."""
    if not native_session_id:
        return
    path = _get_session_map_path()
    if not path:
        return
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
    except OSError as exc:
        logger.warning("Failed to persist session map: %s", exc)


class NormalizeFn(Protocol):
    def __call__(self, event_type: str, data: Mapping[str, Any]) -> NormalizedHookPayload: ...


def _get_adapter(agent: str) -> NormalizeFn:
    if agent == AgentName.CLAUDE.value:
        return claude_adapter.normalize_payload
    if agent == AgentName.CODEX.value:
        return codex_adapter.normalize_payload
    if agent == AgentName.GEMINI.value:
        return gemini_adapter.normalize_payload
    raise ValueError(f"Unknown agent '{agent}'")


def main() -> None:
    args = _parse_args()

    logger.trace(
        "Hook receiver start",
        argv=sys.argv,
        cwd=os.getcwd(),
        stdin_tty=sys.stdin.isatty(),
        has_session_id=bool(_get_env_session_id()),
        agent=args.agent,
    )

    # Read input based on agent type
    if args.agent == AgentName.CODEX.value:
        # Codex notify passes JSON as command-line argument, event is always "stop"
        raw_input = args.event_type or ""
        try:
            raw_data: dict[str, object] = (  # guard: loose-dict - Raw stdin JSON payload.
                json.loads(raw_input) if raw_input.strip() else {}
            )
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from Codex notify argument")
            raw_data = {}
        event_type = "stop"
    else:
        # Claude/Gemini pass event_type as arg, JSON on stdin
        event_type = cast(str, args.event_type)
        raw_input, raw_data = _read_stdin()

    # log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    log_raw = True
    _log_raw_input(raw_input, log_raw=log_raw)

    # Early exit for unhandled events - don't spawn mcp-wrapper
    if event_type not in _HANDLED_EVENTS:
        logger.trace("Hook receiver skipped: unhandled event", event_type=event_type)
        sys.exit(0)

    raw_native_session_id, raw_native_log_file = _extract_native_identity(args.agent, raw_data)

    teleclaude_session_id = _get_env_session_id() or _get_cached_session_id(args.agent, raw_native_session_id)
    teleclaude_session_id = _resolve_or_refresh_session_id(
        teleclaude_session_id,
        raw_native_session_id,
        agent=args.agent,
    )
    if not teleclaude_session_id:
        # No TeleClaude session yet — mint an ID and let core create the headless session.
        # Requires a native session ID to anchor later resolution.
        if not raw_native_session_id:
            sys.exit(0)
        teleclaude_session_id = str(uuid.uuid4())
        _persist_session_map(args.agent, raw_native_session_id, teleclaude_session_id)
    else:
        _persist_session_map(args.agent, raw_native_session_id, teleclaude_session_id)

    # Gemini: only allow session_start and stop into outbox.
    # For other events, exit cleanly (transcript capture only).
    if args.agent == AgentName.GEMINI.value and event_type not in {"session_start", "stop"}:
        logger.debug(
            "Gemini hook metadata updated (event filtered)",
            event_type=event_type,
            session_id=teleclaude_session_id,
        )
        sys.exit(0)

    normalize_payload = _get_adapter(args.agent)
    try:
        normalized = normalize_payload(event_type, raw_data)
        data = normalized.to_dict()
    except Exception as e:
        logger.error("Receiver validation error", error=str(e))
        _send_error_event(
            teleclaude_session_id,
            str(e),
            {
                "agent": args.agent,
                "event_type": event_type,
            },
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

    cwd = getattr(args, "cwd", None)
    if isinstance(cwd, str) and cwd:
        data["cwd"] = cwd

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(timezone.utc).isoformat()
    _enqueue_hook_event(teleclaude_session_id, event_type, data)


if __name__ == MAIN_MODULE:
    main()
