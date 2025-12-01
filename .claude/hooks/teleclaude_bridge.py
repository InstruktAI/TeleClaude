# TeleClaude bridge hook - forwards Claude Code events to TeleClaude daemon
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add hooks directory to path for imports (must be before local imports)
sys.path.insert(0, str(Path(__file__).parent))

from utils.mcp_send import mcp_send  # noqa: E402

LOG_FILE = Path.cwd() / ".claude" / "hooks" / "logs" / "teleclaude_bridge.log"


def log(message: str) -> None:
    """Write log message to file."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] {message}\n")
    except Exception:  # noqa: S110
        pass


def main() -> None:
    """Forward Claude Code events to TeleClaude daemon via MCP."""
    try:
        log("=== Hook triggered ===")

        # Read input
        data = json.load(sys.stdin)
        log(f"Received data: {json.dumps(data)}")

        # Get TeleClaude session ID from environment (set by tmux)
        teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
        if not teleclaude_session_id:
            log("TELECLAUDE_SESSION_ID not found in environment")
            log("This hook is intended to be run from within a TeleClaude terminal session")
            sys.exit(0)

        # Extract event type from hook data
        # Claude Code uses "hook_event_name" for the event type field
        event_type = data.get("hook_event_name", "unknown")

        # Normalize event type to match TeleClaude conventions
        # Claude Code: "SessionStart" -> TeleClaude: "session_start"
        if event_type:
            event_type = event_type.lower()
            if event_type == "sessionstart":
                event_type = "session_start"
        log(f"Event type: {event_type}, TeleClaude session: {teleclaude_session_id[:8]}")

        # Forward event to daemon via MCP
        mcp_send(
            "teleclaude__handle_claude_event",
            {"session_id": teleclaude_session_id, "event_type": event_type, "data": data},
        )

        log(f"Forwarded {event_type} event to daemon")

    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")

    log("=== Hook finished ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
