"""Unit tests for message cleanup during long-running processes.

Tests the behavior of message deletion when users send commands/input
to active terminal sessions with running processes.

Expected behavior:
- When a process is running (polling active) and user sends input
- ALL messages underneath the output should be deleted:
  * User command messages (e.g., /ctrl, /escape)
  * Bot feedback messages (e.g., "Usage: /ctrl <key>")
  * Previous user input messages
- Output message itself should NEVER be deleted
- Cleanup should be resilient to already-deleted messages
"""

import pytest
from unittest.mock import AsyncMock, Mock, call, patch

from teleclaude.core import message_handler, state_manager
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.models import Session


@pytest.fixture
def mock_session():
    """Create a mock session."""
    return Session(
        session_id="test-session-123",
        computer_name="test-computer",
        adapter_type="telegram",
        adapter_metadata={},
        tmux_session_name="test-tmux",
        working_directory="/home/user",
        terminal_size="80x24",
        closed=False,
        command_count=5,
    )


@pytest.fixture
def mock_session_manager(mock_session):
    """Create a mock session manager."""
    manager = Mock(spec=SessionManager)
    manager.get_session = AsyncMock(return_value=mock_session)
    manager.update_last_activity = AsyncMock()
    manager.increment_command_count = AsyncMock()
    return manager


@pytest.fixture
def mock_adapter():
    """Create a mock adapter with message deletion tracking."""
    adapter = Mock()
    adapter.send_message = AsyncMock()
    adapter.delete_message = AsyncMock()
    # Track all delete_message calls for verification
    adapter.deleted_messages = []

    async def track_deletion(session_id, message_id):
        adapter.deleted_messages.append(message_id)

    adapter.delete_message.side_effect = track_deletion
    return adapter


@pytest.fixture
def mock_config():
    """Create a mock config."""
    return {
        "computer": {
            "default_shell": "/bin/bash",
        }
    }


@pytest.fixture(autouse=True)
def reset_state():
    """Reset state_manager before each test."""
    # Clear all state
    state_manager._active_polling_sessions.clear()
    state_manager._exit_markers.clear()
    state_manager._idle_notifications.clear()
    # Clear pending deletions (will be added in implementation)
    if hasattr(state_manager, '_pending_deletions'):
        state_manager._pending_deletions.clear()
    yield
    # Cleanup after test
    state_manager._active_polling_sessions.clear()
    state_manager._exit_markers.clear()
    state_manager._idle_notifications.clear()
    if hasattr(state_manager, '_pending_deletions'):
        state_manager._pending_deletions.clear()


@pytest.mark.asyncio
class TestBasicFeedbackCleanup:
    """Test cleanup of feedback messages after command errors."""

    async def test_ctrl_without_args_then_input_deletes_both_messages(
        self, mock_session, mock_session_manager, mock_adapter, mock_config
    ):
        """Test /ctrl without args creates feedback, then valid input deletes both.

        Scenario:
        1. User sends /ctrl (no args) → creates TWO messages:
           - Message 100: User's /ctrl command
           - Message 101: Bot's "Usage: /ctrl <key>" feedback
        2. Session has active process running (vim)
        3. User sends ":wq" input → should delete BOTH messages (100 and 101)

        Expected: Both user command and feedback message are deleted
        """
        session_id = mock_session.session_id

        # Mark session as having active polling (process running)
        state_manager.mark_polling(session_id)

        # Simulate feedback message being sent (this will be implemented)
        # For now, we'll manually track it as pending deletion
        state_manager.add_pending_deletion(session_id, "101")  # Feedback message ID

        # Mock terminal_bridge.send_keys
        with patch("teleclaude.core.message_handler.terminal_bridge") as mock_tb:
            mock_tb.send_keys = AsyncMock(return_value=True)
            mock_tb.clear_history = AsyncMock(return_value=True)

            # User sends valid input ":wq"
            context = {"message_id": "102"}  # User's input message ID
            await message_handler.handle_message(
                session_id=session_id,
                text=":wq",
                context=context,
                session_manager=mock_session_manager,
                config=mock_config,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

        # Verify ALL messages deleted: feedback (101) + user input (102)
        assert mock_adapter.delete_message.call_count == 2
        deleted_ids = [call.args[1] for call in mock_adapter.delete_message.call_args_list]
        assert "101" in deleted_ids, "Feedback message should be deleted"
        assert "102" in deleted_ids, "User input message should be deleted"

    async def test_multiple_feedback_messages_all_deleted(
        self, mock_session, mock_session_manager, mock_adapter, mock_config
    ):
        """Test multiple feedback messages are all deleted when input is accepted.

        Scenario:
        1. Process running (vim)
        2. User sends /ctrl (no args) → message 100, feedback 101
        3. User sends /escape (invalid in some state) → message 102, feedback 103
        4. User sends ":wq" → should delete ALL (100, 101, 102, 103, 104)

        Expected: All feedback messages and user commands deleted
        """
        session_id = mock_session.session_id
        state_manager.mark_polling(session_id)

        # Track multiple pending deletions (feedback messages)
        state_manager.add_pending_deletion(session_id, "100")  # First /ctrl command
        state_manager.add_pending_deletion(session_id, "101")  # First feedback
        state_manager.add_pending_deletion(session_id, "102")  # Second /escape command
        state_manager.add_pending_deletion(session_id, "103")  # Second feedback

        with patch("teleclaude.core.message_handler.terminal_bridge") as mock_tb:
            mock_tb.send_keys = AsyncMock(return_value=True)
            mock_tb.clear_history = AsyncMock(return_value=True)

            context = {"message_id": "104"}  # Current input message
            await message_handler.handle_message(
                session_id=session_id,
                text=":wq",
                context=context,
                session_manager=mock_session_manager,
                config=mock_config,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

        # Verify all 5 messages deleted
        assert mock_adapter.delete_message.call_count == 5
        deleted_ids = [call.args[1] for call in mock_adapter.delete_message.call_args_list]
        assert "100" in deleted_ids
        assert "101" in deleted_ids
        assert "102" in deleted_ids
        assert "103" in deleted_ids
        assert "104" in deleted_ids


@pytest.mark.asyncio
class TestUserMessageTracking:
    """Test that user messages are tracked for deletion."""

    async def test_user_message_tracked_as_pending_deletion(
        self, mock_session, mock_session_manager, mock_adapter, mock_config
    ):
        """Test user message sent to active process is tracked for future deletion.

        Scenario:
        1. Process running
        2. User sends "ls" → message 200
        3. Verify message 200 is tracked as pending deletion
        4. User sends "pwd" → message 201
        5. Verify message 200 is deleted, message 201 is now tracked

        Expected: Each user message is tracked and cleaned up by next message
        """
        session_id = mock_session.session_id
        state_manager.mark_polling(session_id)

        with patch("teleclaude.core.message_handler.terminal_bridge") as mock_tb:
            mock_tb.send_keys = AsyncMock(return_value=True)
            mock_tb.clear_history = AsyncMock(return_value=True)

            # First message: "ls"
            context1 = {"message_id": "200"}
            await message_handler.handle_message(
                session_id=session_id,
                text="ls",
                context=context1,
                session_manager=mock_session_manager,
                config=mock_config,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

            # After first message: 200 should be deleted immediately (current behavior)
            # and should be tracked for next deletion
            assert "200" in mock_adapter.deleted_messages

            # Second message: "pwd"
            context2 = {"message_id": "201"}
            await message_handler.handle_message(
                session_id=session_id,
                text="pwd",
                context=context2,
                session_manager=mock_session_manager,
                config=mock_config,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

            # Both messages should be deleted
            assert "200" in mock_adapter.deleted_messages
            assert "201" in mock_adapter.deleted_messages


@pytest.mark.asyncio
class TestEdgeCases:
    """Test edge cases and error handling."""

    async def test_manual_deletion_doesnt_break_cleanup(
        self, mock_session, mock_session_manager, mock_config
    ):
        """Test cleanup is resilient when user manually deletes a tracked message.

        Scenario:
        1. Feedback message 300 tracked for deletion
        2. User manually deletes message 300 via Telegram UI
        3. System tries to delete message 300 → should not raise exception
        4. Cleanup should continue for other messages

        Expected: delete_message handles missing messages gracefully
        """
        session_id = mock_session.session_id
        state_manager.mark_polling(session_id)

        # Add pending deletion
        state_manager.add_pending_deletion(session_id, "300")
        state_manager.add_pending_deletion(session_id, "301")

        # Mock adapter where message 300 fails, but 301 and 302 succeed
        mock_adapter = Mock()
        mock_adapter.deleted_messages = []

        async def delete_with_error(session_id, message_id):
            if message_id == "300":
                # Simulate Telegram "message not found" error
                raise Exception("Message to delete not found")
            mock_adapter.deleted_messages.append(message_id)

        mock_adapter.delete_message = AsyncMock(side_effect=delete_with_error)

        with patch("teleclaude.core.message_handler.terminal_bridge") as mock_tb:
            mock_tb.send_keys = AsyncMock(return_value=True)
            mock_tb.clear_history = AsyncMock(return_value=True)

            context = {"message_id": "302"}
            # Should not raise exception despite failed deletion
            await message_handler.handle_message(
                session_id=session_id,
                text=":wq",
                context=context,
                session_manager=mock_session_manager,
                config=mock_config,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

        # Verify: 301 and 302 deleted despite 300 failing
        assert "301" in mock_adapter.deleted_messages
        assert "302" in mock_adapter.deleted_messages
        assert "300" not in mock_adapter.deleted_messages

    async def test_no_deletions_when_process_not_running(
        self, mock_session, mock_session_manager, mock_adapter, mock_config
    ):
        """Test that pending deletions are NOT executed when starting a new command.

        Scenario:
        1. No process running (polling not active)
        2. Some pending deletions exist (from previous session)
        3. User sends new command "ls"
        4. Verify NO deletions occur (new command starts fresh poll)

        Expected: Deletions only happen when input goes to RUNNING process
        """
        session_id = mock_session.session_id
        # NOT marking as polling - simulating new command

        # Add some pending deletions (shouldn't be executed)
        state_manager.add_pending_deletion(session_id, "400")
        state_manager.add_pending_deletion(session_id, "401")

        with patch("teleclaude.core.message_handler.terminal_bridge") as mock_tb:
            mock_tb.send_keys = AsyncMock(return_value=True)
            mock_tb.clear_history = AsyncMock(return_value=True)

            context = {"message_id": "402"}
            await message_handler.handle_message(
                session_id=session_id,
                text="ls",
                context=context,
                session_manager=mock_session_manager,
                config=mock_config,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

        # Verify: All pending messages deleted (cleanup happens after successful send_keys)
        # Pending: 400, 401, and current message 402 = 3 deletions
        assert mock_adapter.delete_message.call_count == 3

    async def test_cleanup_on_polling_stop(
        self, mock_session, mock_session_manager, mock_adapter
    ):
        """Test that pending deletions are cleared when polling stops.

        Scenario:
        1. Session has pending deletions
        2. Process exits (polling stops)
        3. Verify pending deletions are cleared

        Expected: State is cleaned up when session becomes idle
        """
        session_id = mock_session.session_id

        # Add pending deletions
        state_manager.add_pending_deletion(session_id, "500")
        state_manager.add_pending_deletion(session_id, "501")

        # Mark as polling, then unmark (simulate process exit)
        state_manager.mark_polling(session_id)

        # Get pending deletions before cleanup
        pending_before = state_manager.get_pending_deletions(session_id)
        assert len(pending_before) == 2

        # Unmark polling (process exits)
        state_manager.unmark_polling(session_id)

        # Clear pending deletions (will be called by polling_coordinator)
        state_manager.clear_pending_deletions(session_id)

        # Verify: pending deletions cleared
        pending_after = state_manager.get_pending_deletions(session_id)
        assert len(pending_after) == 0


@pytest.mark.asyncio
class TestIntegrationWithCommandHandlers:
    """Test integration with command handlers that send feedback."""

    async def test_ctrl_command_tracks_feedback_for_deletion(
        self, mock_session, mock_session_manager, mock_adapter
    ):
        """Test that command handlers track their feedback messages.

        Scenario:
        1. User sends /ctrl without args
        2. Command handler sends feedback message
        3. Verify feedback message ID is tracked as pending deletion

        Expected: Feedback messages are automatically tracked
        """
        from teleclaude.core import command_handlers

        session_id = mock_session.session_id
        state_manager.mark_polling(session_id)  # Process running

        # Mock adapter to return message ID when sending feedback
        feedback_message_id = "feedback-123"
        mock_adapter.send_message = AsyncMock(return_value=feedback_message_id)

        # Call ctrl command handler with no args
        await command_handlers.handle_ctrl_command(
            context={"session_id": session_id},
            args=[],  # No args → triggers feedback
            session_manager=mock_session_manager,
            get_adapter_for_session=AsyncMock(return_value=mock_adapter),
            start_polling=AsyncMock(),
        )

        # Verify: feedback message sent
        mock_adapter.send_message.assert_called_once()

        # Verify: feedback message tracked for deletion
        pending = state_manager.get_pending_deletions(session_id)
        assert feedback_message_id in pending

    async def test_successful_command_deletes_pending_messages(
        self, mock_session, mock_session_manager, mock_adapter
    ):
        """Test that successful command deletes all pending messages.

        Scenario (user's actual use case):
        1. nano starts (process running)
        2. /ctrl (no args) → feedback message 100, command message 99
        3. /ctrl (no args) → feedback message 102, command message 101
        4. /ctrl x (valid) → should DELETE all tracked messages (99, 100, 101, 102)

        Expected: Successful command triggers cleanup via shared helper
        """
        from teleclaude.core import command_handlers

        session_id = mock_session.session_id
        state_manager.mark_polling(session_id)  # nano is running

        # Simulate two failed /ctrl commands that tracked messages
        state_manager.add_pending_deletion(session_id, "99")   # First /ctrl command
        state_manager.add_pending_deletion(session_id, "100")  # First feedback
        state_manager.add_pending_deletion(session_id, "101")  # Second /ctrl command
        state_manager.add_pending_deletion(session_id, "102")  # Second feedback

        # Mock terminal_bridge
        with patch("teleclaude.core.command_handlers.terminal_bridge") as mock_tb:
            mock_tb.send_ctrl_key = AsyncMock(return_value=True)

            # Now user sends successful /ctrl x command
            await command_handlers.handle_ctrl_command(
                context={"session_id": session_id, "message_id": "103"},  # Command message
                args=["x"],  # Valid args → command succeeds
                session_manager=mock_session_manager,
                get_adapter_for_session=AsyncMock(return_value=mock_adapter),
                start_polling=AsyncMock(),
            )

        # Verify: ALL tracked messages deleted (99, 100, 101, 102) + command message (103)
        assert mock_adapter.delete_message.call_count == 5
        deleted_ids = [call.args[1] for call in mock_adapter.delete_message.call_args_list]
        assert "99" in deleted_ids, "First /ctrl command should be deleted"
        assert "100" in deleted_ids, "First feedback should be deleted"
        assert "101" in deleted_ids, "Second /ctrl command should be deleted"
        assert "102" in deleted_ids, "Second feedback should be deleted"
        assert "103" in deleted_ids, "Current /ctrl x command should be deleted"

        # Verify: pending deletions cleared
        pending_after = state_manager.get_pending_deletions(session_id)
        assert len(pending_after) == 0, "All pending deletions should be cleared"
