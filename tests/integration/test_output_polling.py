"""Test if output polling works end-to-end."""

import asyncio
import tempfile
import os

from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge


async def test_output_flow():
    """Test the full flow of sending a command and polling output."""
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
        tmux_session_name="test-output",
        adapter_type="telegram",
        title="Test Session",
        adapter_metadata={"topic_id": 123},
        terminal_size="80x24",
        working_directory="/tmp"
    )

    print(f"✓ Created session: {session.session_id[:8]}")

    # Create tmux session
    success = await terminal.create_tmux_session(
        name="test-output",
        shell="/bin/zsh",
        working_dir="/tmp",
        cols=80,
        rows=24
    )

    if not success:
        print("✗ Failed to create tmux session")
        return

    print("✓ Created tmux session")

    # Send a command
    print("\nSending command: ls -la")
    await terminal.send_keys("test-output", "ls -la")

    # Now simulate the polling logic from daemon
    print("\nSimulating polling logic...")
    max_message_length = 3800
    scrubber_position = 0
    unchanged_count = 0
    max_unchanged = 3
    max_polls = 10
    poll_interval = 1.0

    output_sent = False

    for poll_count in range(max_polls):
        # Wait before capturing
        await asyncio.sleep(poll_interval)

        # Capture current output
        output = await terminal.capture_pane("test-output")

        print(f"\nPoll {poll_count+1}:")
        print(f"  Output length: {len(output)}")
        print(f"  Scrubber position: {scrubber_position}")
        print(f"  Unchanged count: {unchanged_count}")

        if not output.strip():
            print("  → No output yet, continuing...")
            continue

        # Check if we have new output since last scrubber position
        if len(output) <= scrubber_position:
            # No new output
            unchanged_count += 1
            print(f"  → No new output (unchanged_count={unchanged_count})")
            if unchanged_count >= max_unchanged:
                print(f"  → Output stabilized, stopping poll")
                break
            continue

        # We have new output, reset counter
        unchanged_count = 0

        # Extract new content from scrubber position
        new_content = output[scrubber_position:]
        print(f"  → New content detected: {len(new_content)} chars")
        print(f"  → Preview: {repr(new_content[:100])}")

        # Split into chunks if needed
        chunk_count = 0
        while new_content:
            # Take chunk (respect max length)
            chunk = new_content[:max_message_length]
            new_content = new_content[max_message_length:]

            chunk_count += 1
            print(f"  → Would send chunk {chunk_count}: {len(chunk)} chars")
            output_sent = True

            # Update scrubber position
            scrubber_position += len(chunk)

            # If we have more chunks, add a small delay
            if new_content:
                await asyncio.sleep(0.5)

    # Cleanup
    print("\n\nCleaning up...")
    await terminal.kill_session("test-output")
    await session_manager.delete_session(session.session_id)
    await session_manager.close()

    # Remove temporary database
    try:
        os.unlink(db_path)
    except Exception as e:
        print(f"Warning: Could not remove temp database: {e}")

    if output_sent:
        print("\n✓ Output was successfully detected and would be sent!")
    else:
        print("\n✗ NO output was detected - polling logic failed!")

    return output_sent


if __name__ == "__main__":
    result = asyncio.run(test_output_flow())
    exit(0 if result else 1)
