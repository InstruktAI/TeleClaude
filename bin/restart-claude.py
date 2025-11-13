#!/usr/bin/env python3
"""Restart the most recent Claude Code CLI session."""

import subprocess
import sys
import time


def find_latest_claude_pid():
    """Find PID of most recently started Claude Code process."""
    result = subprocess.run(
        ["ps", "-eo", "pid,etime,tty,comm"],
        capture_output=True,
        text=True,
        check=True,
    )

    claude_procs = []
    for line in result.stdout.splitlines()[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 4 and parts[3] == "claude":
            pid = int(parts[0])
            etime = parts[1]  # Format: [[dd-]hh:]mm:ss
            tty = parts[2]
            claude_procs.append((pid, etime, tty))

    if not claude_procs:
        return None

    def etime_to_seconds(etime_str):
        """Convert ps etime format to seconds."""
        parts = etime_str.replace("-", ":").split(":")
        parts.reverse()  # [ss, mm, hh, dd]
        multipliers = [1, 60, 3600, 86400]
        return sum(int(p) * m for p, m in zip(parts, multipliers))

    # Sort by elapsed time (shortest first = most recent)
    claude_procs.sort(key=lambda x: etime_to_seconds(x[1]))
    return claude_procs[0]  # Return (pid, etime, tty)


def find_tmux_session_for_tty(tty):
    """Find tmux session name for a given TTY."""
    if tty == "??":
        return None

    # Normalize TTY format: ps shows "ttys020", tmux shows "/dev/ttys020"
    if not tty.startswith("/dev/"):
        tty = f"/dev/{tty}"

    result = subprocess.run(
        ["tmux", "list-panes", "-a", "-F", "#{session_name} #{pane_tty}"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            session_name = parts[0]
            pane_tty = parts[1]
            if pane_tty == tty:
                return session_name

    return None


def main():
    """Kill latest Claude process and restart in its tmux session."""
    claude_info = find_latest_claude_pid()

    if not claude_info:
        print("No Claude Code process found")
        sys.exit(1)

    pid, _, tty = claude_info
    print(f"Found latest Claude Code process: PID {pid} on {tty}")

    # Find tmux session
    session_name = find_tmux_session_for_tty(tty)

    # Kill the process
    print(f"Killing PID {pid}...")
    subprocess.run(["kill", str(pid)], check=True)
    time.sleep(2)

    if session_name:
        # Claude is in tmux - auto-restart
        print(f"Found tmux session: {session_name}")
        print(f"Sending restart command to tmux session {session_name}...")
        subprocess.run(
            [
                "tmux",
                "send-keys",
                "-t",
                session_name,
                "claude --dangerously-skip-permissions --continue -m 'continue'",
                "Enter",
            ],
            check=True,
        )
        print("✅ Claude Code restarted in tmux session")
    else:
        # Claude is in direct terminal - can't auto-restart
        print(f"⚠️  Claude was running in a direct terminal (not tmux)")
        print("   Auto-restart only works for TeleClaude tmux sessions")
        print("\n📋 To restart manually, run:")
        print("   claude --dangerously-skip-permissions --continue -m 'continue'")


if __name__ == "__main__":
    main()
