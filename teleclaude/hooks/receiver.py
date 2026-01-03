#!/usr/bin/env python3
"""Unified hook receiver for agent CLIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
from utils.mcp_send import mcp_send  # noqa: E402

from teleclaude.constants import UI_MESSAGE_MAX_CHARS  # noqa: E402

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
    mcp_send(
        "teleclaude__handle_agent_event",
        {
            "session_id": session_id,
            "event_type": "error",
            "data": {"message": message, "source": "hook_receiver", "details": details},
        },
    )


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
        event_type = cast(str, args.event_type)
        raw_input, data = _read_stdin()

    log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    _log_raw_input(raw_input, log_raw=log_raw)

    teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
    if not teleclaude_session_id:
        logger.debug("Hook receiver skipped: missing session id")
        sys.exit(0)

    # Early exit for unhandled events - don't spawn mcp-wrapper
    if event_type not in _HANDLED_EVENTS:
        logger.trace("Hook receiver skipped: unhandled event", event_type=event_type)
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

    mcp_send(
        "teleclaude__handle_agent_event",
        {
            "session_id": teleclaude_session_id,
            "event_type": event_type,
            "data": data,
        },
    )


if __name__ == "__main__":
    main()
