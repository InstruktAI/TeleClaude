#!/usr/bin/env python3
"""Test long-running command with output streaming."""
import asyncio
import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge

async def main():
    """Test long-running command."""
    # Load env
    load_dotenv(".env")

    # Initialize components
    db_path = "sessions.db"
    session_manager = SessionManager(db_path)
    await session_manager.initialize()

    terminal = TerminalBridge()

    # Get first active session
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        print("No active sessions found. Please create a session via Telegram first.")
        print("Send /new-session in the TeleClaude Control supergroup")
        return

    session = sessions[0]
    print(f"Using session: {session.title}")
    print(f"Session ID: {session.session_id[:8]}")
    print(f"tmux session: {session.tmux_session_name}")

    # Send a bash loop that outputs every second for 20 seconds
    command = 'for i in {1..20}; do echo "Output $i of 20 at $(date +%H:%M:%S)"; sleep 1; done'

    print(f"\nSending command: {command}")
    print("Check your Telegram to see live updates!\n")

    success = await terminal.send_keys(session.tmux_session_name, command)

    if success:
        print("✓ Command sent successfully")
        print("Watch your Telegram for live output updates...")
        print("- First 5 seconds: should edit same message")
        print("- After 5 seconds: should send new messages")
    else:
        print("✗ Failed to send command")

    await session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
