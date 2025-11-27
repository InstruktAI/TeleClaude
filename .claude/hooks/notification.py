#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Claude Code hook - sends notification via MCP socket."""

import json
import os
import random
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from utils.mcp_send import mcp_send

MCP_SOCKET = "/tmp/teleclaude.sock"
LOG_FILE = Path.cwd() / ".claude" / "hooks" / "logs" / "notification.log"

NOTIFICATION_MESSAGES = [
    "Your agent needs your input",
    "Ready for your next instruction",
    "Waiting for guidance",
    "Standing by for input",
    "Input needed to proceed",
]


def log(message: str) -> None:
    """Write log message to file."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] {message}\n")
    except:
        pass


def main() -> None:
    """Send notification via MCP socket."""
    try:
        log("=== Hook triggered ===")

        # Read input
        data = json.load(sys.stdin)
        log(f"Received data: {json.dumps(data)}")

        # Get TeleClaude session ID from environment (set by tmux)
        teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
        # get claude session stuff from data
        session_id = data.get("session_id")
        transcript_path = data.get("transcript_path")

        if not teleclaude_session_id:
            log("ERROR: TELECLAUDE_SESSION_ID not found in environment")
            log("This hook must be run from within a TeleClaude terminal session")
            sys.exit(0)

        log(f"TeleClaude session ID: {teleclaude_session_id}")

        # Determine event type based on hook_event_name
        hook_event = data.get("hook_event_name", "")
        log(f"Hook event: {hook_event}")

        if hook_event == "Stop":
            log("Stop event detected")
            # Stop event - spawn background summarizer (fire and forget)
            transcript_path = data.get("transcript_path", "")
            log(f"Transcript path: {transcript_path}")

            hooks_dir = Path(__file__).parent
            summarizer = hooks_dir / "utils" / "summarizer.py"

            if transcript_path and summarizer.exists():
                log(f"Spawning summarizer: {summarizer}")
                # Spawn background process - returns immediately
                proc = subprocess.Popen(
                    ["uv", "run", "--quiet", str(summarizer), teleclaude_session_id, session_id, transcript_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,  # Detach from parent
                )
                log(f"Summarizer spawned with PID: {proc.pid}")
            else:
                log(
                    f"Summarizer not found or no transcript: summarizer_exists={summarizer.exists()}, transcript={bool(transcript_path)}"
                )

            log("SessionEnd event handled, exiting")
            sys.exit(0)  # Return immediately, summarizer runs in background

        elif hook_event == "Notification":
            log("Notification event detected")

            # Get engineer name if available
            engineer_name = os.getenv("ENGINEER_NAME", "").strip()
            log(f"Engineer name: {engineer_name or '(not set)'}")

            # Create notification message with 30% chance to include name
            prefix = f"{engineer_name}, " if engineer_name and random.random() < 0.3 else ""
            # Generate custom message (ignore generic message from Claude Code)
            random_message = random.choice(NOTIFICATION_MESSAGES)
            message = prefix + (random_message[0].lower() + random_message[1:]) if prefix else random_message
            log(f"Generated message: {message}")

            mcp_send(
                "teleclaude__send_notification",
                {
                    "session_id": teleclaude_session_id,
                    "message": message,
                },
            )

        else:
            log(f"Unknown hook event: {hook_event}, ignoring")
            sys.exit(0)

    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")

    log("=== Hook finished ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
