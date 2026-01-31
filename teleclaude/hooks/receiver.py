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


def _update_session_native_fields(
    session_id: str,
    *,
    native_log_file: str | None = None,
    native_session_id: str | None = None,
) -> None:
    """Update native session fields directly on the session row."""
    if not native_log_file and not native_session_id:
        return
    db_path = config.database.path
    from sqlalchemy import create_engine, text
    from sqlmodel import Session as SqlSession

    engine = create_engine(f"sqlite:///{db_path}")
    update_parts: list[str] = []
    params: dict[str, str] = {"session_id": session_id}
    if native_log_file:
        update_parts.append("native_log_file = :native_log_file")
        params["native_log_file"] = native_log_file
    if native_session_id:
        update_parts.append("native_session_id = :native_session_id")
        params["native_session_id"] = native_session_id
    if not update_parts:
        return

    sql = f"UPDATE sessions SET {', '.join(update_parts)} WHERE session_id = :session_id"
    statement = text(sql).bindparams(**params)
    with SqlSession(engine) as session:
        session.exec(text("PRAGMA journal_mode = WAL"))
        session.exec(text("PRAGMA busy_timeout = 5000"))
        session.exec(statement)
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


def _get_teleclaude_session_id() -> str | None:
    tmpdir = os.getenv("TMPDIR")
    if not tmpdir:
        return None
    candidate = Path(tmpdir) / "teleclaude_session_id"
    if not candidate.exists():
        return None
    try:
        session_id = candidate.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return session_id or None


def _create_headless_session(
    agent: str,
    native_session_id: str | None,
    native_log_file: str | None,
) -> str:
    """Create a headless session row for standalone agent usage (no TeleClaude context).

    Headless sessions have no tmux, no adapter metadata, and no Telegram channel.
    They exist solely to anchor voice assignment and enable summarization and TTS.
    """
    db_path = config.database.path
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    from sqlalchemy import create_engine
    from sqlalchemy import text as sa_text
    from sqlmodel import Session as SqlSession

    engine = create_engine("sqlite:///" + str(db_path))
    with SqlSession(engine) as session:
        session.exec(sa_text("PRAGMA journal_mode = WAL"))
        session.exec(sa_text("PRAGMA busy_timeout = 5000"))
        session.exec(
            sa_text(
                "INSERT INTO sessions "
                "(session_id, computer_name, title, tmux_session_name, "
                "last_input_origin, lifecycle_status, active_agent, "
                "native_session_id, native_log_file, created_at, last_activity) "
                "VALUES (:sid, :computer, :title, :tmux, :origin, :status, :agent, "
                ":native_sid, :native_log, :now, :now)"
            ),
            params={
                "sid": session_id,
                "computer": config.computer.name,
                "title": "Standalone",
                "tmux": None,
                "origin": "standalone",
                "status": "headless",
                "agent": agent,
                "native_sid": native_session_id,
                "native_log": native_log_file,
                "now": now,
            },
        )
        session.commit()

    logger.info(
        "Created headless session",
        session_id=session_id[:8],
        agent=agent,
        native_session_id=(native_session_id or "")[:8],
    )
    return session_id


def _persist_teleclaude_session_id(session_id: str) -> None:
    """Write TC session ID to TMPDIR so subsequent hooks from the same agent session reuse it."""
    tmpdir = os.getenv("TMPDIR")
    if not tmpdir:
        return
    try:
        Path(tmpdir, "teleclaude_session_id").write_text(session_id, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to persist teleclaude_session_id: %s", exc)


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
        has_session_id=bool(_get_teleclaude_session_id()),
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

    teleclaude_session_id = _get_teleclaude_session_id()
    if not teleclaude_session_id:
        # No TeleClaude session — create a headless session for standalone TTS/summarization.
        # Requires a native session ID to anchor the session row.
        if not raw_native_session_id:
            sys.exit(0)
        teleclaude_session_id = _create_headless_session(
            agent=args.agent,
            native_session_id=raw_native_session_id,
            native_log_file=raw_native_log_file,
        )
        _persist_teleclaude_session_id(teleclaude_session_id)

    native_log_file = raw_native_log_file or cast(str | None, raw_data.get("transcript_path"))
    native_session_id = raw_native_session_id or cast(str | None, raw_data.get("session_id"))
    if native_log_file is not None:
        native_log_file = native_log_file.strip() or None
    if native_session_id is not None:
        native_session_id = native_session_id.strip() or None
    if native_log_file or native_session_id:
        try:
            _update_session_native_fields(
                teleclaude_session_id,
                native_log_file=native_log_file,
                native_session_id=native_session_id,
            )
            logger.debug(
                "Hook metadata updated",
                event_type=event_type,
                session_id=teleclaude_session_id,
                agent=args.agent,
            )
        except Exception as exc:  # Best-effort update; never fail hook.
            logger.warning(
                "Hook metadata update failed (ignored)",
                event_type=event_type,
                session_id=teleclaude_session_id,
                agent=args.agent,
                error=str(exc),
            )

    # Gemini: only allow session_start and stop into outbox.
    # For other events, update native log metadata directly (if provided) and exit cleanly.
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

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(timezone.utc).isoformat()
    _enqueue_hook_event(teleclaude_session_id, event_type, data)


if __name__ == MAIN_MODULE:
    main()
