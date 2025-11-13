#!/usr/bin/env python3
"""Restart Claude Code in its TeleClaude session.

Queries TeleClaude database to find the session running Claude,
then sends restart command to that session's tmux.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def main():
    """Find Claude's TeleClaude session and restart it."""
    debug_log = Path.home() / ".claude" / "hooks" / "logs" / "restart_debug.log"
    debug_log.parent.mkdir(parents=True, exist_ok=True)

    # Get Claude session ID from environment (set by Claude Code)
    claude_session_id = os.getenv("CLAUDE_SESSION_ID")
    if not claude_session_id:
        print("ERROR: CLAUDE_SESSION_ID environment variable not set")
        print("This script must be run from within a Claude Code session")
        sys.exit(1)

    try:
        # Find TeleClaude's database
        teleclaude_db = Path.home().parent / "Documents" / "Workspace" / "morriz" / "teleclaude" / "teleclaude.db"
        if not teleclaude_db.exists():
            print(f"ERROR: TeleClaude database not found at {teleclaude_db}")
            with open(debug_log, "a") as f:
                f.write(f"TeleClaude database not found at {teleclaude_db}\n")
            sys.exit(1)

        # Query for session with this claude_session_id
        conn = sqlite3.connect(str(teleclaude_db))
        cursor = conn.execute(
            "SELECT session_id, tmux_session_name FROM sessions WHERE json_extract(ux_state, '$.claude_session_id') = ?",
            (claude_session_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            print(f"ERROR: No TeleClaude session found for Claude session {claude_session_id}")
            with open(debug_log, "a") as f:
                f.write(f"No TeleClaude session found for Claude session {claude_session_id}\n")
            sys.exit(1)

        teleclaude_session_id, tmux_session = row
        print(f"Found TeleClaude session: {teleclaude_session_id[:8]} (tmux: {tmux_session})")

        # Send restart command to tmux session
        restart_cmd = "claude --dangerously-skip-permissions --continue -m 'continue'"
        result = subprocess.run(
            ["tmux", "send-keys", "-t", tmux_session, restart_cmd, "Enter"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode == 0:
            print(f"✅ Restart command sent to tmux session {tmux_session}")
            with open(debug_log, "a") as f:
                f.write(f"✅ Restarted Claude in session {teleclaude_session_id[:8]} (tmux: {tmux_session})\n")
        else:
            print(f"❌ Failed to send restart command: {result.stderr}")
            with open(debug_log, "a") as f:
                f.write(f"❌ Failed to send restart command: {result.stderr}\n")
            sys.exit(1)

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        with open(debug_log, "a") as f:
            f.write(f"Exception restarting Claude: {type(e).__name__}: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
