#!/usr/bin/env python3
"""Test script to trigger daemon commands directly."""

import pytest


@pytest.mark.asyncio
async def test_new_session_creates_session_and_tmux(daemon_with_mocked_telegram):
    """Test /new_session command creates database entry and tmux session."""
    daemon = daemon_with_mocked_telegram

    # Verify no sessions exist initially
    initial_sessions = await daemon.session_manager.list_sessions()
    assert len(initial_sessions) == 0, "Should start with no sessions"

    # Execute command
    context = {
        "adapter_type": "telegram",
        "user_id": 12345,
        "chat_id": -67890,
        "message_thread_id": None
    }
    await daemon.handle_command("new-session", ["Test", "Session"], context)

    # Verify session was created in database
    sessions = await daemon.session_manager.list_sessions()
    assert len(sessions) == 1, "Should create exactly one session"

    session = sessions[0]
    assert session.title == "[TestComputer] Test Session"
    assert session.computer_name == "TestComputer"
    assert session.status == "active"
    assert session.adapter_type == "telegram"

    # Verify tmux session exists
    tmux_exists = await daemon.terminal.session_exists(session.tmux_session_name)
    assert tmux_exists, f"tmux session {session.tmux_session_name} should exist"

    # Verify mocks were called
    daemon.telegram.create_channel.assert_called_once()
    assert daemon.telegram.send_message.call_count >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
