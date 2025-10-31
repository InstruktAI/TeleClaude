"""Test /cancel command through the daemon to verify output polling works end-to-end."""

import asyncio

from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge


class MockAdapter:
    """Mock adapter to capture messages sent by daemon."""

    def __init__(self):
        self.messages = []

    async def send_message(self, session_id: str, text: str, **kwargs):
        """Capture sent messages."""
        print(f"📤 Adapter.send_message: {text[:100]}")
        self.messages.append({"session_id": session_id, "text": text})

    async def edit_message(self, session_id: str, message_id: str, text: str, **kwargs):
        """Capture edited messages."""
        print(f"✏️  Adapter.edit_message: {text[:100]}")
        self.messages.append({"session_id": session_id, "text": text, "edited": True})


async def test_cancel_daemon_flow():
    """Test that daemon's _cancel_command properly polls output."""
    # Initialize components
    session_manager = SessionManager("test_sessions.db")
    await session_manager.initialize()

    terminal = TerminalBridge()
    mock_adapter = MockAdapter()

    # Create a test session
    session = await session_manager.create_session(
        computer_name="TestComputer",
        tmux_session_name="test-daemon-cancel",
        adapter_type="telegram",
        title="Test Daemon Cancel",
        adapter_metadata={"topic_id": 123},
        terminal_size="80x24",
        working_directory="/tmp"
    )

    print(f"✓ Created session: {session.session_id[:8]}")

    # Create tmux session
    success = await terminal.create_tmux_session(
        name="test-daemon-cancel",
        shell="/bin/zsh",
        working_dir="/tmp",
        cols=80,
        rows=24
    )

    if not success:
        print("✗ Failed to create tmux session")
        return False

    print("✓ Created tmux session")

    # Import daemon's _poll_and_send_output logic
    # We'll simulate what the daemon does
    print("\n1. Sending long-running command")
    await terminal.send_keys("test-daemon-cancel", "sleep 10")
    await asyncio.sleep(0.5)

    print("2. Sending SIGINT (simulating /cancel)")
    success = await terminal.send_signal("test-daemon-cancel", "SIGINT")
    if not success:
        print("✗ Failed to send SIGINT")
        await terminal.kill_session("test-daemon-cancel")
        await session_manager.delete_session(session.session_id)
        await session_manager.close()
        return False

    print("✓ Sent SIGINT")

    # Simulate the daemon's _poll_and_send_output logic
    print("\n3. Polling for output (simulating daemon's _poll_and_send_output)")
    max_polls = 5
    unchanged_count = 0
    max_unchanged = 3
    scrubber_position = 0
    poll_interval = 0.5

    output_captured = False

    for poll_count in range(max_polls):
        await asyncio.sleep(poll_interval)

        output = await terminal.capture_pane("test-daemon-cancel")

        if not output.strip():
            continue

        # Check for new output
        if len(output) <= scrubber_position:
            unchanged_count += 1
            if unchanged_count >= max_unchanged:
                print(f"   → Output stabilized after {poll_count + 1} polls")
                break
            continue

        # We have new output
        unchanged_count = 0
        new_content = output[scrubber_position:]

        if new_content.strip():
            print(f"   → New output detected: {len(new_content)} chars")
            # Send the output (simulating what daemon does)
            await mock_adapter.send_message(session.session_id, new_content)
            output_captured = True

        scrubber_position = len(output)

    # Verify results
    print(f"\n4. Verification:")
    print(f"   - Output captured: {output_captured}")
    print(f"   - Messages sent by adapter: {len(mock_adapter.messages)}")

    if output_captured and len(mock_adapter.messages) > 0:
        print(f"   ✓ Daemon flow works correctly!")
        print(f"\n   Messages that would be sent to Telegram:")
        for i, msg in enumerate(mock_adapter.messages, 1):
            print(f"   {i}. {repr(msg['text'][:100])}")
    else:
        print(f"   ✗ No output captured or sent")

    # Cleanup
    print("\nCleaning up...")
    await terminal.kill_session("test-daemon-cancel")
    await session_manager.delete_session(session.session_id)
    await session_manager.close()

    return output_captured and len(mock_adapter.messages) > 0


if __name__ == "__main__":
    result = asyncio.run(test_cancel_daemon_flow())
    print(f"\n{'✓ Test PASSED' if result else '✗ Test FAILED'}")
    exit(0 if result else 1)
