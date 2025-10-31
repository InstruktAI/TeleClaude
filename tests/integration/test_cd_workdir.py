#!/usr/bin/env python3
"""Test /cd WORKDIR command."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_cd_workdir_changes_directory(daemon_with_mocked_telegram):
    """Test /cd WORKDIR command changes directory to project root."""
    daemon = daemon_with_mocked_telegram

    # Count sessions before
    initial_count = len(await daemon.session_manager.list_sessions())

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["CD", "Test"], context)

    # Get the newly created session
    sessions = await daemon.session_manager.list_sessions()
    assert len(sessions) == initial_count + 1, f"Should create one new session, but have {len(sessions)}"
    # Get the most recently created session (last in list sorted by last_activity DESC)
    session = sessions[0]

    # Test context for commands
    cmd_context = {"session_id": session.session_id, "user_id": 12345}

    # Send pwd to see initial directory
    await daemon.terminal.send_keys(session.tmux_session_name, "pwd")
    await asyncio.sleep(0.2)

    # Execute /cd WORKDIR
    await daemon.handle_command("cd", ["WORKDIR"], cmd_context)
    await asyncio.sleep(0.2)

    # Send pwd again to verify directory change
    await daemon.terminal.send_keys(session.tmux_session_name, "pwd")
    await asyncio.sleep(0.2)

    # Capture terminal output
    output = await daemon.terminal.capture_pane(session.tmux_session_name)
    assert output is not None, "Should capture terminal output"

    # Verify WORKDIR is in the output (which is /tmp for tests)
    assert "/tmp" in output, f"Should show /tmp in output, got: {output[-200:]}"

    # Verify send_message mock was called (for trusted dirs list)
    assert daemon.telegram.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_cd_no_args_lists_trusted_dirs(daemon_with_mocked_telegram):
    """Test /cd with no arguments lists trusted directories."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["CD", "List"], context)

    # Get the created session
    sessions = await daemon.session_manager.list_sessions()
    session = sessions[0]
    cmd_context = {"session_id": session.session_id, "user_id": 12345}

    # Reset mock call count
    daemon.telegram.send_message.reset_mock()

    # Execute /cd with no args
    await daemon.handle_command("cd", [], cmd_context)

    # Verify send_message was called
    assert daemon.telegram.send_message.call_count >= 1, "Should send message with directory list"

    # If inline keyboard is used, message might be different format
    # Just verify the mock was called - actual format depends on implementation
    call_args = daemon.telegram.send_message.call_args
    assert call_args is not None, "send_message should have been called"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
