"""Unit tests for message_handler module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import message_handler
from teleclaude.core.models import Session


@pytest.mark.asyncio
class TestHandleMessage:
    """Test handle_message function."""

    async def test_session_not_found(self):
        """Test message handler when session doesn't exist."""
        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=None)

        config = {"computer": {"default_shell": "/bin/bash"}}
        get_adapter_for_session = AsyncMock()
        start_polling = AsyncMock()

        context = {"message_id": "123"}

        # Execute
        await message_handler.handle_message(
            session_id="nonexistent",
            text="test command",
            context=context,
            session_manager=session_manager,
            config=config,
            get_adapter_for_session=get_adapter_for_session,
            start_polling=start_polling,
        )

        # Verify no further processing
        get_adapter_for_session.assert_not_called()
        start_polling.assert_not_called()

    async def test_delete_idle_notification_when_exists(self):
        """Test that idle notification is deleted when user sends message."""
        session = Session(
            session_id="test-123",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        adapter.delete_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {"message_id": "123"}            # Idle notification exists
            mock_state.has_idle_notification = Mock(return_value=True)
            mock_state.remove_idle_notification = Mock(return_value="idle-msg-456")
            mock_state.is_polling = Mock(return_value=False)
            mock_state.set_exit_marker = Mock()
            mock_state.cleanup_messages_after_success = AsyncMock()

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                mock_terminal.send_keys = AsyncMock(return_value=True)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute
                await message_handler.handle_message(
                    session_id="test-123",
                    text="echo test",
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify idle notification deleted
                mock_state.remove_idle_notification.assert_called_once_with("test-123")
                adapter.delete_message.assert_called_with("test-123", "idle-msg-456")

    async def test_strip_leading_double_slash(self):
        """Test stripping leading // from command (Telegram workaround)."""
        session = Session(
            session_id="test-slash",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {}            mock_state.has_idle_notification = Mock(return_value=False)
            mock_state.is_polling = Mock(return_value=False)
            mock_state.set_exit_marker = Mock()
            mock_state.cleanup_messages_after_success = AsyncMock()

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                mock_terminal.send_keys = AsyncMock(return_value=True)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute with leading //
                await message_handler.handle_message(
                    session_id="test-slash",
                    text="//command",  # Leading double slash
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify send_keys called with stripped text (/command)
                call_args = mock_terminal.send_keys.call_args
                assert call_args[0][1] == "/command"  # Second positional arg is the text

    async def test_terminal_size_parsing_invalid(self):
        """Test handling of invalid terminal size format."""
        session = Session(
            session_id="test-456",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80xABC",  # Invalid format (letters instead of numbers)
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {}            mock_state.has_idle_notification = Mock(return_value=False)
            mock_state.is_polling = Mock(return_value=False)
            mock_state.set_exit_marker = Mock()
            mock_state.cleanup_messages_after_success = AsyncMock()

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                mock_terminal.send_keys = AsyncMock(return_value=True)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute
                await message_handler.handle_message(
                    session_id="test-456",
                    text="echo test",
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify send_keys called with default size (80x24) due to ValueError
                mock_terminal.send_keys.assert_called_once()
                call_kwargs = mock_terminal.send_keys.call_args[1]
                assert call_kwargs["cols"] == 80
                assert call_kwargs["rows"] == 24

    async def test_send_keys_failure(self):
        """Test error handling when terminal send_keys fails."""
        session = Session(
            session_id="test-789",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {}            mock_state.has_idle_notification = Mock(return_value=False)
            mock_state.is_polling = Mock(return_value=False)

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                # send_keys fails
                mock_terminal.send_keys = AsyncMock(return_value=False)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute
                await message_handler.handle_message(
                    session_id="test-789",
                    text="invalid command",
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify error message sent
                adapter.send_message.assert_called_once_with("test-789", "Failed to send command to terminal")

                # Verify no activity updates
                session_manager.update_last_activity.assert_not_called()
                session_manager.increment_command_count.assert_not_called()

                # Verify no polling started
                start_polling.assert_not_called()

    async def test_delete_user_message_when_polling_active(self):
        """Test user message is deleted when sending input to running process."""
        session = Session(
            session_id="test-999",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        adapter.delete_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {"message_id": "555"}            mock_state.has_idle_notification = Mock(return_value=False)
            # Process is running (polling active)
            mock_state.is_polling = Mock(return_value=True)
            mock_state.set_exit_marker = Mock()
            mock_state.cleanup_messages_after_success = AsyncMock()
            # No pending deletions (new behavior)
            mock_state.get_pending_deletions = Mock(return_value=[])
            mock_state.clear_pending_deletions = Mock()

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                mock_terminal.send_keys = AsyncMock(return_value=True)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute
                await message_handler.handle_message(
                    session_id="test-999",
                    text="input to running process",
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify cleanup called with user message ID
                mock_state.cleanup_messages_after_success.assert_called_once_with("test-999", "555", adapter)

                # Verify exit marker set to False (not appended)
                mock_state.set_exit_marker.assert_called_once_with("test-999", False)

                # Verify send_keys called with append_exit_marker=False
                call_kwargs = mock_terminal.send_keys.call_args[1]
                assert call_kwargs["append_exit_marker"] is False

                # Verify NO new polling started (existing poll continues)
                start_polling.assert_not_called()

    async def test_user_message_no_delete_if_no_message_id(self):
        """Test user message not deleted if context has no message_id."""
        session = Session(
            session_id="test-111",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        adapter.delete_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {}  # No message_id            mock_state.has_idle_notification = Mock(return_value=False)
            mock_state.is_polling = Mock(return_value=True)
            mock_state.set_exit_marker = Mock()
            mock_state.cleanup_messages_after_success = AsyncMock()
            # No pending deletions
            mock_state.get_pending_deletions = Mock(return_value=[])
            mock_state.clear_pending_deletions = Mock()

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                mock_terminal.send_keys = AsyncMock(return_value=True)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute
                await message_handler.handle_message(
                    session_id="test-111",
                    text="input",
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify cleanup called with None message_id
                mock_state.cleanup_messages_after_success.assert_called_once_with("test-111", None, adapter)

    async def test_new_command_starts_polling(self):
        """Test starting new poll when sending new command (not input to running process)."""
        session = Session(
            session_id="test-222",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.increment_command_count = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()
        config = {"computer": {"default_shell": "/bin/bash"}}
        context = {}            mock_state.has_idle_notification = Mock(return_value=False)
            # No process running
            mock_state.is_polling = Mock(return_value=False)
            mock_state.set_exit_marker = Mock()
            mock_state.cleanup_messages_after_success = AsyncMock()

            with patch("teleclaude.core.message_handler.terminal_bridge") as mock_terminal:
                mock_terminal.send_keys = AsyncMock(return_value=True)
                mock_terminal.clear_history = AsyncMock(return_value=True)

                # Execute
                await message_handler.handle_message(
                    session_id="test-222",
                    text="echo hello",
                    context=context,
                    session_manager=session_manager,
                    config=config,
                    get_adapter_for_session=get_adapter_for_session,
                    start_polling=start_polling,
                )

                # Verify exit marker set to True (appended)
                mock_state.set_exit_marker.assert_called_once_with("test-222", True)

                # Verify send_keys called with append_exit_marker=True
                call_kwargs = mock_terminal.send_keys.call_args[1]
                assert call_kwargs["append_exit_marker"] is True

                # Verify polling started
                start_polling.assert_called_once_with("test-222", "test-tmux")
