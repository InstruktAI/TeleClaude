#!/usr/bin/env python3
"""Test Claude Code integration."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from teleclaude.daemon import TeleClaudeDaemon


async def test_claude_code():
    """Test Claude Code command submission."""
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    daemon = TeleClaudeDaemon(str(base_dir / "config.yml"), str(base_dir / ".env"))

    await daemon.session_manager.initialize()

    sessions = await daemon.session_manager.get_sessions_by_adapter_metadata("telegram", "topic_id", 63)

    if not sessions:
        print("TC TESTS session not found!")
        await daemon.session_manager.close()
        return

    session = sessions[0]
    tmux = session.tmux_session_name

    # Start Claude Code
    print("Starting Claude Code...")
    await daemon.terminal.send_keys(tmux, "claude --dangerously-skip-permissions")
    await asyncio.sleep(5)  # Wait for Claude Code to load

    # Capture initial state
    output = await daemon.terminal.capture_pane(tmux)
    print(f"Claude Code started:\n{output[-300:]}")

    # Send a test command
    print("\nSending command: 'echo hello from telegram'")
    await daemon.terminal.send_keys(tmux, "echo hello from telegram")
    await asyncio.sleep(3)

    # Capture output
    output = await daemon.terminal.capture_pane(tmux)
    print(f"\nAfter command:\n{output[-300:]}")

    # Check if command was executed
    if "Thundering" in output or "Thinking" in output:
        print("\n✓ SUCCESS: Command submitted to Claude Code!")
    else:
        print("\n✗ FAILED: Command may not have submitted")

    await daemon.session_manager.close()


if __name__ == "__main__":
    asyncio.run(test_claude_code())
