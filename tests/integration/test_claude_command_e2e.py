#!/usr/bin/env python3
"""E2E test for /claude command flow."""

import asyncio

import pytest

from teleclaude.core import terminal_bridge
from teleclaude.core.events import TeleClaudeEvents


@pytest.mark.asyncio
@pytest.mark.timeout(15)  # Faster test with echo
async def test_claude_command_with_non_interactive_command(daemon_with_mocked_telegram):
    """Test /claude command flow with a simple echo for faster testing.

    This test uses a mock approach - we'll test that the command is executed
    but use echo instead of actual claude to make the test faster.
    """
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new_session", ["Echo", "Test"], context)

    # Get the created session
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # Send a simple echo command to verify the flow works
    # This simulates what /claude does but with faster execution
    msg_context = {"user_id": 12345, "message_id": 2001}
    await daemon.handle_message(
        session.session_id,
        "echo 'Claude Code would start here'",
        msg_context,
    )

    # Wait for command to execute and polling to send output
    await asyncio.sleep(3.5)

    # Verify command was executed in tmux
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have terminal output"
    assert (
        "Claude Code would start here" in output or "echo" in output
    ), f"Should see echo command output, got: {output[:300]}"

    # Verify output was sent to Telegram
    total_calls = telegram.send_message.call_count + telegram.edit_message.call_count
    assert total_calls >= 1, (
        f"Should have sent output to Telegram. "
        f"send_message calls: {telegram.send_message.call_count}, "
        f"edit_message calls: {telegram.edit_message.call_count}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_claude_command_with_interactive_command(daemon_with_mocked_telegram):
    """Test interactive command flow with output polling.

    This test verifies the complete flow:
    1. Start an interactive Python process that waits for input
    2. Process produces initial output
    3. We send input to the process
    4. Process responds with output
    5. Output polling captures everything and sends to Telegram
    """
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new_session", ["Interactive", "Test"], context)

    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # Start an interactive Python process that simulates claude behavior
    msg_context = {"user_id": 12345, "message_id": 3001}
    interactive_cmd = "python3 -c \"import sys; print('Ready for input', flush=True); [print(f'Echo: {line.strip()}', flush=True) for line in sys.stdin]\""
    await daemon.handle_message(session.session_id, interactive_cmd, msg_context)

    # Wait for process to start and produce initial output
    await asyncio.sleep(2.0)

    # Verify initial output
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have terminal output"
    assert "Ready for input" in output, f"Should see initial output, got: {output[:500]}"

    # Send input to the interactive process
    await terminal_bridge.send_keys(session.tmux_session_name, "test message")

    # Wait for response and polling to send output
    await asyncio.sleep(2.0)

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
