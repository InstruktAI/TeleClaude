#!/usr/bin/env python3
"""Gemini CLI hook receiver.

Receives events from Gemini CLI, normalizes them, and forwards to TeleClaude.
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
LOG_FILE = LOG_DIR / "receiver_gemini.log"


def log(message: str) -> None:
    """Write log message to file."""
    try:
        append_line(LOG_FILE, f"[{datetime.now().isoformat()}] {message}")
    except Exception:
        pass


def main() -> None:
    try:
        log("=== Gemini Receiver Triggered ===")

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

        # Get event type from args (passed by setup_gemini_hooks.py)
        event_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"

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
