#!/usr/bin/env python3
"""Test script to send a message to TC TESTS session."""

import asyncio
import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from teleclaude.daemon import TeleClaudeDaemon

async def test_send_message():
    """Test sending message to TC TESTS session."""
    # Load environment
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    # Create daemon instance
    daemon = TeleClaudeDaemon(
        str(base_dir / "config.yml"),
        str(base_dir / ".env")
    )

    # Initialize
    await daemon.session_manager.initialize()

    # Get TC TESTS session
    sessions = await daemon.session_manager.get_sessions_by_adapter_metadata(
        "telegram", "topic_id", 63
    )

    if not sessions:
        print("TC TESTS session not found!")
        await daemon.session_manager.close()
        return

    session = sessions[0]
    print(f"Found session: {session.title}")
    print(f"tmux session: {session.tmux_session_name}")

    # Send command directly to tmux
    success = await daemon.terminal.send_keys(session.tmux_session_name, "echo test123")
    print(f"Command sent: {success}")

    # Wait for output
    await asyncio.sleep(1)

    # Capture output
    output = await daemon.terminal.capture_pane(session.tmux_session_name)
    print(f"Output captured ({len(output)} chars):")
    print(output[-200:] if len(output) > 200 else output)

    # Cleanup
    await daemon.session_manager.close()

if __name__ == "__main__":
    asyncio.run(test_send_message())
