#!/usr/bin/env python3
"""E2E tests for command execution with mocked commands (short-lived and long-running)."""

import asyncio

import pytest

from teleclaude.core import terminal_bridge


@pytest.mark.asyncio
@pytest.mark.timeout(12)
async def test_short_lived_command(daemon_with_mocked_telegram):
    """Test short-lived command execution flow.

    Verifies:
    1. Command executes quickly (mocked with echo)
    2. Output is captured and sent to Telegram
    3. Command completes immediately
    """
    daemon = daemon_with_mocked_telegram

    # Default mode is "short" - no need to set it
    assert daemon.mock_command_mode == "short"

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new_session", ["Short", "Test"], context)

    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # Send any command - it will be mocked with short echo
    msg_context = {"user_id": 12345, "message_id": 2001}
    await daemon.handle_message(session.session_id, "any command here", msg_context)

    # Wait for command to execute and polling to send output
    await asyncio.sleep(3.3)

    # Verify command was executed in tmux
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have terminal output"
    assert "Command executed" in output, f"Should see mocked command output, got: {output[:300]}"

    # Verify output was sent to Telegram
    total_calls = telegram.send_message.call_count + telegram.edit_message.call_count
    assert total_calls >= 1, (
        f"Should have sent output to Telegram. "
        f"send_message calls: {telegram.send_message.call_count}, "
        f"edit_message calls: {telegram.edit_message.call_count}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(12)
async def test_long_running_command(daemon_with_mocked_telegram):
    """Test long-running interactive command flow.

    Verifies:
    1. Long-running process starts and waits for input
    2. Initial output is captured
    3. Bidirectional communication works (send input, get response)
    4. Output polling captures all interactions
    """
    daemon = daemon_with_mocked_telegram

    # Set mode to long-running for this test
    daemon.mock_command_mode = "long"

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new_session", ["Long", "Test"], context)

    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # Send any command - it will be mocked with long-running Python process
    msg_context = {"user_id": 12345, "message_id": 3001}
    await daemon.handle_message(session.session_id, "any command", msg_context)

    # Wait for process to start and produce initial output
    await asyncio.sleep(0.01)

    # Verify initial output
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have terminal output"
    assert "Ready" in output, f"Should see initial output, got: {output[:500]}"

    # For the second send (sending input to running process), temporarily disable mock
    daemon.mock_command_mode = "passthrough"

    try:
        # Send input to the interactive process
        await terminal_bridge.send_keys(session.tmux_session_name, "test message")

        # Wait for response and polling to send output to Telegram
        await asyncio.sleep(3.3)

        # Verify terminal has both initial output and response
        output = await terminal_bridge.capture_pane(session.tmux_session_name)
        assert "Echo: test message" in output, f"Should see response to input, got: {output[:500]}"

        # Verify output was sent to Telegram
        total_calls = telegram.send_message.call_count + telegram.edit_message.call_count
        assert total_calls >= 1, (
            f"Should have sent output to Telegram. "
            f"send_message calls: {telegram.send_message.call_count}, "
            f"edit_message calls: {telegram.edit_message.call_count}"
        )
    finally:
        # CRITICAL: Reset mock mode to prevent subsequent tests from running real commands
        daemon.mock_command_mode = "short"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
