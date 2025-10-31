"""Test terminal polling to understand the issue."""

import asyncio

from teleclaude.core.terminal_bridge import TerminalBridge


async def test_polling():
    """Test polling behavior with tmux."""
    bridge = TerminalBridge()

    # Create test session
    session_name = "test-polling"
    print(f"Creating tmux session: {session_name}")

    success = await bridge.create_tmux_session(
        name=session_name,
        shell="/bin/zsh",
        working_dir="/tmp",
        cols=80,
        rows=24
    )

    if not success:
        print("Failed to create session")
        return

    print("✓ Session created")

    # Send a simple command
    print("\nSending command: echo 'Hello World'")
    await bridge.send_keys(session_name, "echo 'Hello World'")

    # Poll multiple times and see what we get
    for i in range(5):
        await asyncio.sleep(0.5)
        output = await bridge.capture_pane(session_name)
        print(f"\n--- Poll {i+1} (length={len(output)}) ---")
        print(repr(output[:200]))  # Show first 200 chars

    # Send another command
    print("\n\nSending command: ls -la")
    await bridge.send_keys(session_name, "ls -la")

    # Poll again
    for i in range(5):
        await asyncio.sleep(0.5)
        output = await bridge.capture_pane(session_name)
        print(f"\n--- Poll {i+1} after ls (length={len(output)}) ---")
        print(repr(output[:200]))

    # Cleanup
    print("\n\nCleaning up...")
    await bridge.kill_session(session_name)
    print("✓ Session killed")


if __name__ == "__main__":
    asyncio.run(test_polling())
