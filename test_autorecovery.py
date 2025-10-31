#!/usr/bin/env python3
"""Test auto-recovery for /claude command."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from teleclaude.daemon import TeleClaudeDaemon


async def test_auto_recovery():
    """Test that /claude command auto-recovers when session is gone."""

    # Initialize daemon
    daemon = TeleClaudeDaemon()
    await daemon.start()

    try:
        # Find TC TESTS session
        sessions = await daemon.session_manager.list_sessions()
        test_session = None
        for session in sessions:
            if session.title and "TC TESTS" in session.title:
                test_session = session
                break

        if not test_session:
            print("❌ No TC TESTS session found. Create one first with /new-session TC TESTS")
            return

        print(f"✅ Found TC TESTS session: {test_session.session_id}")
        print(f"   Tmux session: {test_session.tmux_session_name}")

        # Check if tmux session exists
        exists_before = await daemon.terminal.session_exists(test_session.tmux_session_name)
        print(f"   Tmux exists before: {exists_before}")

        if exists_before:
            # Kill the tmux session to simulate it being gone
            print(f"\n🔪 Killing tmux session to test auto-recovery...")
            killed = await daemon.terminal.kill_session(test_session.tmux_session_name)
            print(f"   Kill result: {killed}")

            # Verify it's gone
            exists_after_kill = await daemon.terminal.session_exists(test_session.tmux_session_name)
            print(f"   Tmux exists after kill: {exists_after_kill}")

        # Now call /claude command with auto_recover enabled
        print(f"\n🚀 Calling /claude command (should auto-recover)...")
        context = {
            "session_id": test_session.session_id,
            "adapter_type": test_session.adapter_type
        }

        await daemon._claude_session(context)

        # Check if tmux session was recreated
        exists_after_claude = await daemon.terminal.session_exists(test_session.tmux_session_name)
        print(f"   Tmux exists after /claude: {exists_after_claude}")

        if exists_after_claude:
            print("✅ Auto-recovery successful! Session was recreated.")

            # Capture output to verify claude command was sent
            await asyncio.sleep(2)  # Wait for command to execute
            output = await daemon.terminal.capture_pane(test_session.tmux_session_name, lines=50)

            if "claude" in output.lower():
                print("✅ Claude command appears in output!")
                print("\nOutput preview:")
                print("-" * 60)
                print(output[:500])
                print("-" * 60)
            else:
                print("⚠️  Claude command not found in output")
        else:
            print("❌ Auto-recovery failed - session not recreated")

    finally:
        # Clean up
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(test_auto_recovery())
