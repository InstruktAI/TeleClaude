#!/usr/bin/env python3
"""Claude Code hook receiver.

Receives events from Claude Code, normalizes them, and forwards to TeleClaude.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path to find utils
sys.path.append(str(Path(__file__).parent))

from utils.file_log import append_line
from utils.mcp_send import mcp_send

# Log to project's logs directory (hooks are in teleclaude/hooks/, so go up 2 levels)
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "receiver_claude.log"


def log(message: str) -> None:
    """Write log message to file."""
    try:
        append_line(LOG_FILE, f"[{datetime.now().isoformat()}] {message}")
    except Exception:
        pass


def main() -> None:
    try:
        log("=== Claude Receiver Triggered ===")

        # Read input from stdin
        try:
            if not sys.stdin.isatty():
                data = json.load(sys.stdin)
            else:
                data = {}
        except json.JSONDecodeError:
            log("Failed to parse JSON from stdin")
            data = {}

        # Get TeleClaude session ID
        teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
        if not teleclaude_session_id:
            log("No TELECLAUDE_SESSION_ID, ignoring")
            sys.exit(0)

        def send_error(message: str, details: dict[str, object] | None = None) -> None:
            mcp_send(
                "teleclaude__handle_agent_event",
                {
                    "session_id": teleclaude_session_id,
                    "event_type": "error",
                    "data": {"message": message, "source": "claude_hook", "details": details or {}},
                },
            )

        # Extract event type (prefer argv to avoid missing hook_event_name)
        if len(sys.argv) > 1:
            event_type = sys.argv[1]
        else:
            event_type = str(data.get("hook_event_name", "unknown"))
        event_type = event_type.lower()
        if event_type == "sessionstart":
            event_type = "session_start"

        log(f"Event: {event_type}, Session: {teleclaude_session_id[:8]}")

        allowed_events = {"session_start", "notification", "stop"}
        if event_type not in allowed_events:
            msg = f"Unknown hook event_type '{event_type}'"
            log(msg)
            send_error(msg, {"event_type": event_type})
            sys.exit(1)

        if event_type == "session_start":
            native_session_id = data.get("session_id")
            transcript_path = data.get("transcript_path")
            if not native_session_id or not transcript_path:
                msg = "session_start missing required fields: session_id and transcript_path"
                log(msg)
                send_error(msg, {"data_keys": list(data.keys())})
                sys.exit(1)

        # Forward to TeleClaude
        mcp_send(
            "teleclaude__handle_agent_event",
            {"session_id": teleclaude_session_id, "event_type": event_type, "data": data},
        )

    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
