#!/usr/bin/env python3
"""E2E test for /claude command flow."""

import asyncio

import pytest

from teleclaude.core import terminal_bridge
from teleclaude.core.events import TeleClaudeEvents


@pytest.mark.asyncio
@pytest.mark.timeout(30)  # Claude Code startup needs more time
async def test_claude_command_starts_and_sends_output(daemon_with_mocked_telegram):
    """Test /claude command: starts claude in tmux, polls output, sends to Telegram.

    This test verifies the complete flow:
    1. TG adapter receives /claude command
    2. Event is emitted and handled
    3. Claude Code starts in tmux session
    4. Output polling begins
    5. First output is sent to Telegram API
    """
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new_session", ["Claude", "Test"], context)

    # Get the created session
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # Simulate /claude command from Telegram
    claude_context = {
        "session_id": session.session_id,
        "adapter_type": "telegram",
        "user_id": 12345,
        "message_id": 1001,
    }

    # Send /claude command (with --help to get quick output and exit)
    await daemon.handle_command(
        TeleClaudeEvents.CLAUDE,
        ["--help"],  # Use --help for fast, predictable output
        claude_context,
    )

    # Wait for claude to start and produce initial output
    # Claude Code with --help should complete quickly
    await asyncio.sleep(5.0)

    # Verify claude command was executed in tmux
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have terminal output"

    # Verify claude command ran (should see either the command or help output)
    assert (
        "claude" in output.lower() or "help" in output.lower() or "usage" in output.lower()
    ), f"Should see claude command or help output in terminal, got: {output[:500]}"

    # Verify output was sent to Telegram
    # Either send_message or edit_message should have been called
    total_calls = telegram.send_message.call_count + telegram.edit_message.call_count
    assert total_calls >= 1, (
        f"Should have sent at least one message to Telegram. "
        f"send_message calls: {telegram.send_message.call_count}, "
        f"edit_message calls: {telegram.edit_message.call_count}"
    )


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
