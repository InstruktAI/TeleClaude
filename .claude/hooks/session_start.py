# make it send
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from utils.mcp_send import mcp_send

LOG_FILE = Path.cwd() / ".claude" / "hooks" / "logs" / "session_start.log"


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
    """Send init via MCP socket and inject env vars."""
    try:
        log("=== Hook triggered ===")

        # Read input
        data = json.load(sys.stdin)
        log(f"Received data: {json.dumps(data)}")

        # Get Claude session info
        claude_session_id = data.get("session_id")
        claude_session_file = data.get("transcript_path")

        # Inject Claude session info into environment (for restart_claude.py)
        claude_env_file = os.getenv("CLAUDE_ENV_FILE")
        if claude_env_file:
            with open(claude_env_file, "a", encoding="utf-8") as f:
                f.write(f'export CLAUDE_SESSION_ID="{claude_session_id}"\n')
                f.write(f'export CLAUDE_SESSION_FILE="{claude_session_file}"\n')
            log(f"Injected CLAUDE_SESSION_ID into environment: {claude_session_id[:8]}")
        else:
            log("WARNING: CLAUDE_ENV_FILE not set - cannot inject env vars")

        # Get TeleClaude session ID from environment (set by tmux)
        teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
        if not teleclaude_session_id:
            log("TELECLAUDE_SESSION_ID not found in environment")
            log("This hook is intended to be run from within a TeleClaude terminal session")
            sys.exit(0)

        log(f"TeleClaude session ID: {teleclaude_session_id}")

        # Update database via MCP
        mcp_send(
            "teleclaude__init_from_claude",
            {
                "session_id": teleclaude_session_id,
                "claude_session_id": claude_session_id,
                "claude_session_file": claude_session_file,
            },
        )

    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")

    log("=== Hook finished ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
