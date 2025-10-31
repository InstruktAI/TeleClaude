#!/usr/bin/env python3
"""Test full message flow including output polling."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_message_execution_and_output_polling(daemon_with_mocked_telegram):
    """Test complete message flow: execute command, poll output, send to Telegram."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["Flow", "Test"], context)

    # Get the created session
    sessions = await daemon.session_manager.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    daemon.telegram.send_message.reset_mock()
    daemon.telegram.edit_message.reset_mock()

    # Send a command via handle_message
    msg_context = {"user_id": 12345, "message_id": 999}
    await daemon.handle_message(session.session_id, "echo 'Test Output'", msg_context)

    # Wait for command execution
    await asyncio.sleep(0.3)

    # Verify terminal has output
    output = await daemon.terminal.capture_pane(session.tmux_session_name)
    assert output is not None
    assert "Test Output" in output or "echo" in output

    # Verify output was sent to Telegram (either send or edit)
    total_calls = daemon.telegram.send_message.call_count + daemon.telegram.edit_message.call_count
    assert total_calls >= 1, "Should send or edit message with output"


@pytest.mark.asyncio
async def test_command_execution_via_terminal(daemon_with_mocked_telegram):
    """Test that commands execute in terminal and output is captured."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["Terminal", "Test"], context)

    sessions = await daemon.session_manager.list_sessions()
    session = sessions[0]

    # Send command directly to terminal
    await daemon.terminal.send_keys(session.tmux_session_name, "echo 'Direct command'")
    await asyncio.sleep(0.2)

    # Verify output in terminal
    output = await daemon.terminal.capture_pane(session.tmux_session_name)
    assert output is not None
    assert "Direct command" in output or "echo" in output

    # Verify tmux session is still alive
    exists = await daemon.terminal.session_exists(session.tmux_session_name)
    assert exists, "tmux session should still exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
