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

        # Extract event type (Claude specific)
        event_type = data.get("hook_event_name", "unknown").lower()
        if event_type == "sessionstart":
            event_type = "session_start"

        log(f"Event: {event_type}, Session: {teleclaude_session_id[:8]}")

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
