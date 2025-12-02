# TeleClaude bridge hook - forwards Claude Code events to TeleClaude daemon
#
# This is the ONLY place that communicates with TeleClaude.
# All Claude Code events flow through here via teleclaude__handle_claude_event.
import json
import os
import random
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add hooks directory to path for imports (must be before local imports)
sys.path.insert(0, str(Path(__file__).parent))

from utils.mcp_send import mcp_send  # noqa: E402

LOG_FILE = Path.cwd() / ".claude" / "hooks" / "logs" / "teleclaude_bridge.log"

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
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] {message}\n")
    except Exception:  # noqa: S110
        pass


def send_event(teleclaude_session_id: str, event_type: str, data: dict) -> None:
    """Send event to TeleClaude daemon via MCP."""
    mcp_send(
        "teleclaude__handle_claude_event",
        {"session_id": teleclaude_session_id, "event_type": event_type, "data": data},
    )
    log(f"Sent {event_type} event to daemon")


def handle_notification(teleclaude_session_id: str) -> None:
    """Handle notification event - generate message and send via event."""
    engineer_name = os.getenv("ENGINEER_NAME", "").strip()
    log(f"Engineer name: {engineer_name or '(not set)'}")

    # Create notification message with 30% chance to include name
    prefix = f"{engineer_name}, " if engineer_name and random.random() < 0.3 else ""
    random_message = random.choice(NOTIFICATION_MESSAGES)
    message = prefix + (random_message[0].lower() + random_message[1:]) if prefix else random_message
    log(f"Generated notification: {message}")

    # Send as event - daemon handles the actual notification
    send_event(teleclaude_session_id, "notification", {"message": message})


def run_summarizer(transcript_path: str) -> dict:
    """Run summarizer utility and return parsed JSON result.

    Returns:
        Dict with "summary" and "title" keys, or "error" key on failure.
    """
    hooks_dir = Path(__file__).parent
    summarizer = hooks_dir / "utils" / "summarizer.py"

    if not summarizer.exists():
        log(f"Summarizer not found: {summarizer}")
        return {"error": "Summarizer not found"}

    log(f"Running summarizer: {summarizer}")

    try:
        result = subprocess.run(
            ["uv", "run", "--quiet", str(summarizer), transcript_path],
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout for API calls
        )

        if result.returncode != 0:
            log(f"Summarizer failed: {result.stderr}")
            return {"error": result.stderr or "Summarizer failed"}

        output = result.stdout.strip()
        log(f"Summarizer output: {output}")

        return json.loads(output)

    except subprocess.TimeoutExpired:
        log("Summarizer timed out")
        return {"error": "Summarizer timed out"}
    except json.JSONDecodeError as e:
        log(f"Invalid JSON from summarizer: {e}")
        return {"error": f"Invalid JSON: {e}"}
    except Exception as e:
        log(f"Summarizer error: {e}")
        return {"error": str(e)}


def handle_stop(teleclaude_session_id: str, transcript_path: str, original_data: dict) -> None:
    """Handle stop event - run summarizer and send summary event."""
    # First forward the original stop event
    send_event(teleclaude_session_id, "stop", original_data)

    if not transcript_path:
        log("No transcript path, skipping summarizer")
        return

    # Run summarizer and get result
    result = run_summarizer(transcript_path)

    if "error" in result:
        log(f"Summarizer failed: {result['error']}")
        # Send default summary on error
        result = {"summary": "Work complete!", "title": None}

    # Send summary event - daemon handles notification and title update
    send_event(teleclaude_session_id, "summary", result)


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

        # Route to appropriate handler
        if event_type == "notification":
            handle_notification(teleclaude_session_id)
        elif event_type == "stop":
            transcript_path = data.get("transcript_path", "")
            handle_stop(teleclaude_session_id, transcript_path, data)
        else:
            # Forward other events directly
            send_event(teleclaude_session_id, event_type, data)

    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")

    log("=== Hook finished ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
