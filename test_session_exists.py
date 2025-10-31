#!/usr/bin/env python3
"""Test why session_exists returns False when session exists."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from teleclaude.core.terminal_bridge import TerminalBridge


async def test_session_exists():
    """Test session_exists detection."""

    bridge = TerminalBridge()
    session_name = "mozbook-session-9edf8050"

    print(f"Testing session: {session_name}\n")

    # Test 1: List all sessions
    print("Test 1: List all tmux sessions")
    sessions = await bridge.list_tmux_sessions()
    print(f"Sessions found: {sessions}")
    print(f"Target session in list: {session_name in sessions}\n")

    # Test 2: Check session_exists
    print("Test 2: Check session_exists()")
    exists = await bridge.session_exists(session_name)
    print(f"session_exists() returned: {exists}\n")

    # Test 3: Raw subprocess call
    print("Test 3: Raw subprocess call to tmux has-session")
    proc = await asyncio.create_subprocess_exec(
        "tmux", "has-session", "-t", session_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    print(f"Return code: {proc.returncode}")
    print(f"Stdout: {stdout.decode()}")
    print(f"Stderr: {stderr.decode()}")


if __name__ == "__main__":
    asyncio.run(test_session_exists())
