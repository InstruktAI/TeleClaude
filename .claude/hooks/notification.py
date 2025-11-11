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
from pathlib import Path

MCP_SOCKET = "/tmp/teleclaude.sock"

NOTIFICATION_MESSAGES = [
    "Your agent needs your input",
    "Ready for your next instruction",
    "Waiting for guidance",
    "Standing by for input",
    "Input needed to proceed",
]


def main() -> None:
    """Send notification via MCP socket."""
    try:
        # Read input
        data = json.load(sys.stdin)
        session_id = data.get("session_id")

        if not session_id:
            sys.exit(0)

        # Determine event type and handle accordingly
        if data.get("stop_hook_active") or data.get("transcript_path"):
            # Stop event - spawn background summarizer (fire and forget)
            transcript_path = data.get("transcript_path", "")
            hooks_dir = Path(__file__).parent
            summarizer = hooks_dir / "scripts" / "summarizer.py"

            if transcript_path and summarizer.exists():
                # Spawn background process - returns immediately
                subprocess.Popen(
                    ["uv", "run", "--quiet", str(summarizer), session_id, transcript_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,  # Detach from parent
                )
            sys.exit(0)  # Return immediately, summarizer runs in background

        elif data.get("message") == "Claude is waiting for your input":
            # Skip generic notification message
            sys.exit(0)

        else:
            # Get engineer name if available
            engineer_name = os.getenv("ENGINEER_NAME", "").strip()

            # Create notification message with 30% chance to include name
            prefix = f"{engineer_name}, " if engineer_name and random.random() < 0.3 else ""
            # Notification event - send random message
            message = prefix + random.choice(NOTIFICATION_MESSAGES)

            # Pipe to mcp_send.py
            hooks_dir = Path(__file__).parent
            mcp_send = hooks_dir / "scripts" / "mcp_send.py"

            payload = json.dumps({"session_id": session_id, "message": message})
            subprocess.run(
                ["uv", "run", "--quiet", str(mcp_send)],
                input=payload,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    except:
        pass  # Fail silently

    sys.exit(0)


if __name__ == "__main__":
    main()
