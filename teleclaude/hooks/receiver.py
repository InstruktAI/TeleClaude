#!/usr/bin/env python3
"""Unified hook receiver for agent CLIs."""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
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
from teleclaude.constants import UI_MESSAGE_MAX_CHARS  # noqa: E402
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
        choices=("claude", "codex", "gemini"),
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

    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hook_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
                attempt_count INTEGER DEFAULT 0,
                last_error TEXT,
                delivered_at TEXT,
                locked_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO hook_outbox (
                session_id, event_type, payload, created_at, next_attempt_at, attempt_count
            ) VALUES (?, ?, ?, ?, ?, 0)
            """,
            (session_id, event_type, payload_json, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _extract_native_identity(agent: str, data: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Extract native session id + transcript path from raw hook payload."""
    native_session_id: str | None = None
    native_log_file: str | None = None

    if agent == "codex":
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


class NormalizeFn(Protocol):
    def __call__(self, event_type: str, data: Mapping[str, Any]) -> NormalizedHookPayload: ...


def _get_adapter(agent: str) -> NormalizeFn:
    if agent == "claude":
        return claude_adapter.normalize_payload
    if agent == "codex":
        return codex_adapter.normalize_payload
    if agent == "gemini":
        return gemini_adapter.normalize_payload
    raise ValueError(f"Unknown agent '{agent}'")


def _normalize_event_type(agent: str, event_type: str | None) -> str | None:
    if event_type is None:
        return None

    normalized = event_type.strip().lower().replace("-", "_")

    if agent == "gemini":
        if normalized == "after_agent":
            return "stop"
        if normalized == "before_agent":
            return "prompt"

    if agent == "claude":
        if normalized == "user_prompt_submit":
            return "prompt"

    return event_type


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
    if args.agent == "codex":
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
        event_type = _normalize_event_type(args.agent, cast(str, args.event_type))
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
        # No TeleClaude session found - this is valid for standalone sessions
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

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(timezone.utc).isoformat()
    _enqueue_hook_event(teleclaude_session_id, event_type, data)


if __name__ == "__main__":
    main()
