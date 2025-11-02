#!/usr/bin/env python3
"""Test /rename command."""

import pytest


@pytest.mark.asyncio
async def test_rename_updates_session_title(daemon_with_mocked_telegram):
    """Test /rename command updates session title in database."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["Old", "Title"], context)

    # Get the created session
    sessions = await daemon.session_manager.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.title == "# TestComputer - Old Title"

    # Execute rename command
    cmd_context = {"session_id": session.session_id, "user_id": 12345}
    daemon.telegram.update_channel_title.reset_mock()

    await daemon.handle_command("rename", ["New", "Name"], cmd_context)

    # Verify title was updated in database
    updated_session = await daemon.session_manager.get_session(session.session_id)
    assert updated_session is not None
    assert updated_session.title == "[TestComputer] New Name"

    # Verify Telegram channel title was updated
    daemon.telegram.update_channel_title.assert_called_once()


@pytest.mark.asyncio
async def test_rename_with_single_word(daemon_with_mocked_telegram):
    """Test /rename command with single word title."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["Initial"], context)

    sessions = await daemon.session_manager.list_sessions()
    session = sessions[0]

    # Rename to single word
    cmd_context = {"session_id": session.session_id, "user_id": 12345}
    await daemon.handle_command("rename", ["SingleWord"], cmd_context)

    # Verify
    updated_session = await daemon.session_manager.get_session(session.session_id)
    assert updated_session.title == "[TestComputer] SingleWord"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
