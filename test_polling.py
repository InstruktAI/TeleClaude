#!/usr/bin/env python3
"""Test polling with long-running command."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge

async def main():
    """Send test command to active session."""
    load_dotenv(".env")

    session_manager = SessionManager("sessions.db")
    await session_manager.initialize()
    terminal = TerminalBridge()

    # Get active sessions
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        print("❌ No active sessions")
        return

    session = sessions[0]
    print(f"✓ Using session: {session.title}")
    print(f"  tmux: {session.tmux_session_name}")

    # Send long-running test command
    cmd = 'for i in {1..20}; do echo "Output $i/20 at $(date +%H:%M:%S)"; sleep 1; done'
    print(f"\n✓ Sending: {cmd}")

    success = await terminal.send_keys(session.tmux_session_name, cmd)

    if success:
        print("✓ Command sent! Check Telegram for live updates")
        print("  → Should see ONE message that grows every second")
        print("  → No duplicate messages")
    else:
        print("❌ Failed to send command")

    await session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
