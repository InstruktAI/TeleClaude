#!/usr/bin/env python3
"""Unified hook receiver for agent CLIs."""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

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
from teleclaude.core.db import (  # noqa: E402
    get_session_id_by_field_sync,
    get_session_id_by_tmux_name_sync,
)

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Only these events are forwarded to MCP. All others are silently dropped.
# This prevents zombie mcp-wrapper processes from intermediate hooks.
_HANDLED_EVENTS: frozenset[str] = frozenset(
    {
        "session_start",
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


def _read_stdin() -> tuple[str, dict[str, object]]:  # noqa: loose-dict - Agent hook stdin data
    raw_input = ""
    data: dict[str, object] = {}  # noqa: loose-dict - Agent hook stdin data
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
    details: dict[str, object],  # noqa: loose-dict - Error detail data
) -> None:
    _enqueue_hook_event(
        session_id,
        "error",
        {"message": message, "source": "hook_receiver", "details": details},
    )


def _get_parent_process_info() -> tuple[int | None, str | None]:
    """Capture parent PID + controlling TTY for hook caller.

    Walk the parent process chain and select the most reliable TTY owner.
    Prefer a shell parent when available; fall back to the nearest TTY-holding ancestor.
    """
    parent_pid = os.getppid()
    if parent_pid <= 1:
        parent_pid = None

    def _normalize_tty(value: str | None) -> str | None:
        if not value:
            return None
        tty = value if value.startswith("/dev/") else f"/dev/{value}"
        return tty if Path(tty).exists() else None

    def _stdio_tty() -> str | None:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                if stream is not None and stream.isatty():
                    return _normalize_tty(os.ttyname(stream.fileno()))
            except Exception:
                continue
        return None

    stdio_tty = _stdio_tty()

    try:
        import psutil  # type: ignore[import-not-found]

        if parent_pid:
            shell_names = {
                "bash",
                "zsh",
                "fish",
                "sh",
                "ksh",
                "tcsh",
                Path(os.environ.get("SHELL") or "").name,
            }

            chain = []
            proc = psutil.Process(parent_pid)
            while proc and proc.pid > 1 and len(chain) < 50:
                chain.append(proc)
                try:
                    proc = proc.parent()
                except Exception:
                    break

            # Prefer a shell process with a tty.
            for proc in chain:
                tty = _normalize_tty(proc.terminal() if hasattr(proc, "terminal") else None)
                if not tty:
                    continue
                try:
                    name = proc.name()
                except Exception:
                    name = ""
                if name in shell_names:
                    return proc.pid, tty

            # Fallback to the nearest ancestor with a tty.
            for proc in chain:
                tty = _normalize_tty(proc.terminal() if hasattr(proc, "terminal") else None)
                if tty:
                    return proc.pid, tty
    except Exception:
        pass

    if parent_pid:
        try:
            result = subprocess.run(
                ["ps", "-o", "tty=", "-p", str(parent_pid)],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            tty_name = result.stdout.strip()
            tty_path = _normalize_tty(tty_name)
            if tty_path:
                return parent_pid, tty_path
        except Exception:
            pass

    ssh_tty = _normalize_tty(os.getenv("SSH_TTY"))
    if ssh_tty:
        return parent_pid, ssh_tty

    if stdio_tty:
        return parent_pid, stdio_tty

    return parent_pid, None


def _enqueue_hook_event(
    session_id: str,
    event_type: str,
    data: dict[str, object],  # noqa: loose-dict - Hook payload is dynamic JSON
) -> None:
    """Persist hook event to local outbox for durable delivery."""
    db_path = config.database.path
    now = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(data)

    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
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


def _extract_native_identity(agent: str, data: dict[str, object]) -> tuple[str | None, str | None]:  # noqa: loose-dict - Raw hook payload
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


def _find_session_by_native_id(native_session_id: str) -> str | None:
    """Locate a TeleClaude session by stored native_session_id."""
    return get_session_id_by_field_sync(config.database.path, "native_session_id", native_session_id)


def _find_session_by_log_path(native_log_file: str) -> str | None:
    """Locate a TeleClaude session by stored native_log_file."""
    return get_session_id_by_field_sync(config.database.path, "native_log_file", native_log_file)


def _find_session_by_tmux_name(tmux_name: str) -> str | None:
    """Locate a TeleClaude session by tmux session name."""
    return get_session_id_by_tmux_name_sync(config.database.path, tmux_name)


def _session_exists(session_id: str) -> bool:
    """Return True if a TeleClaude session exists in the DB."""
    db_path = config.database.path
    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        try:
            cursor = conn.execute("SELECT 1 FROM sessions WHERE session_id = ? LIMIT 1", (session_id,))
            return cursor.fetchone() is not None
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return False
            raise
    finally:
        conn.close()


class NormalizeFn(Protocol):
    def __call__(self, event_type: str, data: dict[str, object]) -> dict[str, object]: ...  # noqa: loose-dict - Agent hook protocol


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
    if agent != "gemini":
        return event_type
    normalized = event_type.strip().lower().replace("-", "_")
    if normalized == "after_agent":
        return "stop"
    return event_type


def main() -> None:
    args = _parse_args()

    logger.trace(
        "Hook receiver start",
        argv=sys.argv,
        cwd=os.getcwd(),
        stdin_tty=sys.stdin.isatty(),
        has_session_id="TELECLAUDE_SESSION_ID" in os.environ,
        agent=args.agent,
    )

    # Read input based on agent type
    if args.agent == "codex":
        # Codex notify passes JSON as command-line argument, event is always "stop"
        raw_input = args.event_type or ""
        try:
            data: dict[str, object] = json.loads(raw_input) if raw_input.strip() else {}  # noqa: loose-dict - Agent hook data
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from Codex notify argument")
            data = {}
        event_type = "stop"
    else:
        # Claude/Gemini pass event_type as arg, JSON on stdin
        event_type = _normalize_event_type(args.agent, cast(str, args.event_type))
        raw_input, data = _read_stdin()

    log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    _log_raw_input(raw_input, log_raw=log_raw)

    # Early exit for unhandled events - don't spawn mcp-wrapper
    if event_type not in _HANDLED_EVENTS:
        logger.trace("Hook receiver skipped: unhandled event", event_type=event_type)
        sys.exit(0)

    raw_native_session_id, raw_native_log_file = _extract_native_identity(args.agent, data)

    parent_pid, tty_path = _get_parent_process_info()

    teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
    if teleclaude_session_id and not _session_exists(teleclaude_session_id):
        logger.warning(
            "Hook receiver session id missing in DB; attempting recovery",
            session_id=teleclaude_session_id,
        )
        teleclaude_session_id = None

    if not teleclaude_session_id:
        tmux_name = None
        if os.getenv("TMUX"):
            try:
                tmux_result = subprocess.run(
                    [config.computer.tmux_binary, "display-message", "-p", "#{session_name}"],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                    check=False,
                )
                tmux_name = tmux_result.stdout.strip() if tmux_result.returncode == 0 else None
            except Exception:
                tmux_name = None

        if tmux_name:
            teleclaude_session_id = _find_session_by_tmux_name(tmux_name)
            if teleclaude_session_id:
                logger.info(
                    "Hook receiver recovered session from tmux",
                    session_id=teleclaude_session_id,
                    tmux_session=tmux_name,
                )

        if not teleclaude_session_id:
            if raw_native_session_id:
                teleclaude_session_id = _find_session_by_native_id(raw_native_session_id)
            if not teleclaude_session_id and raw_native_log_file:
                teleclaude_session_id = _find_session_by_log_path(raw_native_log_file)
            if teleclaude_session_id:
                logger.info(
                    "Hook receiver recovered session from native id",
                    session_id=teleclaude_session_id,
                    native_session_id=raw_native_session_id,
                )
            else:
                # No TeleClaude session found - this is valid for standalone Claude sessions
                sys.exit(0)

    normalize_payload = _get_adapter(args.agent)
    try:
        data = normalize_payload(event_type, data)
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

    normalized_native_session_id = data.get("session_id") if isinstance(data.get("session_id"), str) else None
    normalized_log_file = data.get("transcript_path") if isinstance(data.get("transcript_path"), str) else None
    logger.debug(
        "Hook payload summary",
        event_type=event_type,
        agent=args.agent,
        session_id=teleclaude_session_id,
        raw_native_session_id=raw_native_session_id,
        raw_transcript_path=raw_native_log_file,
        normalized_native_session_id=normalized_native_session_id,
        normalized_transcript_path=normalized_log_file,
        transcript_missing=bool(event_type == "session_start" and not normalized_log_file),
    )

    if parent_pid:
        data["teleclaude_pid"] = parent_pid
    if tty_path:
        data["teleclaude_tty"] = tty_path

    data["agent_name"] = args.agent
    _enqueue_hook_event(teleclaude_session_id, event_type, data)


if __name__ == "__main__":
    main()
