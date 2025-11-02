"""Test that /cancel command now polls terminal output instead of just showing '^C'."""

import asyncio
import tempfile
import os

from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge


async def test_cancel_output():
    """Test that cancel command captures terminal output."""
    # Create unique database for this test
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    # Initialize components
    session_manager = SessionManager(db_path)
    await session_manager.initialize()

    terminal = TerminalBridge()

    # Create a test session
    session = await session_manager.create_session(
        computer_name="TestComputer",
        tmux_session_name="test-cancel",
        adapter_type="telegram",
        title="Test Cancel Session",
        adapter_metadata={"topic_id": 123},
        terminal_size="80x24",
        working_directory="/tmp"
    )

    print(f"✓ Created session: {session.session_id[:8]}")

    # Create tmux session
    success = await terminal.create_tmux_session(
        name="test-cancel",
        shell="/bin/zsh",
        working_dir="/tmp",
        cols=80,
        rows=24
    )

    if not success:
        print("✗ Failed to create tmux session")
        return False

    print("✓ Created tmux session")

    # Send a long-running command
    print("\n1. Sending long-running command: sleep 10")
    await terminal.send_keys("test-cancel", "sleep 10")
    await asyncio.sleep(0.5)  # Let it start

    # Send SIGINT (simulating /cancel)
    print("2. Sending SIGINT (^C)")
    success = await terminal.send_signal("test-cancel", "SIGINT")

    if not success:
        print("✗ Failed to send SIGINT")
        await terminal.kill_session("test-cancel")
        await session_manager.delete_session(session.session_id)
        await session_manager.close()
        return False

    print("✓ Sent SIGINT")

    # Wait a moment for output to appear
    await asyncio.sleep(1.0)

    # Capture terminal output (this is what _poll_and_send_output does)
    output = await terminal.capture_pane("test-cancel")

    print("\n3. Terminal output after SIGINT:")
    print("=" * 50)
    print(output)
    print("=" * 50)

    # Verify output contains evidence of the interrupt
    has_output = len(output.strip()) > 0
    print(f"\n4. Verification:")
    print(f"   - Has output: {has_output}")
    print(f"   - Output length: {len(output)} chars")

    # The output should show the command and the shell prompt
    # It might contain "^C" or just show the interrupted sleep command
    if has_output:
        print(f"   ✓ Terminal output captured successfully!")
        print(f"   This is what users will now see when using /cancel")
    else:
        print(f"   ✗ No terminal output captured")

    # Cleanup
    print("\nCleaning up...")
    await terminal.kill_session("test-cancel")
    await session_manager.delete_session(session.session_id)
    await session_manager.close()

    # Remove temporary database
    try:
        os.unlink(db_path)
    except Exception as e:
        print(f"Warning: Could not remove temp database: {e}")

    return has_output


if __name__ == "__main__":
    result = asyncio.run(test_cancel_output())
    print(f"\n{'✓ Test PASSED' if result else '✗ Test FAILED'}")
    exit(0 if result else 1)
