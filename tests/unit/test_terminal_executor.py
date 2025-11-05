"""Unit tests for terminal_executor module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import terminal_executor
from teleclaude.core.models import Session


@pytest.mark.asyncio
class TestExecuteTerminalCommand:
    """Test execute_terminal_command function."""

    async def test_execute_success_with_exit_marker(self):
        """Test successful command execution with exit marker."""
        # Mock dependencies
        session_manager = Mock()
        session = Session(
            session_id="test-123",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.cleanup_messages_after_success = AsyncMock()

        config = {"computer": {"default_shell": "/bin/bash"}}
        get_adapter_for_session = AsyncMock()
        start_polling = AsyncMock()

        # Mock terminal_bridge
        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-123",
                command="echo hello",
                session_manager=session_manager,
                config=config,
                get_adapter_for_session=get_adapter_for_session,
                start_polling=start_polling,
                append_exit_marker=True,
            )

            # Verify success
            assert result is True

            # Verify terminal_bridge.send_keys called with correct args
            mock_terminal.send_keys.assert_called_once_with(
                "test-tmux",
                "echo hello",
                shell="/bin/bash",
                working_dir="/tmp",
                cols=80,
                rows=24,
                append_exit_marker=True,
            )

            # Verify activity updated
            session_manager.update_last_activity.assert_called_once_with("test-123")

            # Verify polling started
            start_polling.assert_called_once_with("test-123", "test-tmux")

    async def test_execute_success_without_exit_marker(self):
        """Test successful command execution without exit marker (no polling)."""
        session_manager = Mock()
        session = Session(
            session_id="test-456",
            computer_name="TestMac",
            tmux_session_name="test-tmux-2",
            adapter_type="telegram",
            title="Test",
            terminal_size="120x30",
            working_directory="/home",
        )
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.cleanup_messages_after_success = AsyncMock()

        config = {"computer": {"default_shell": "/bin/zsh"}}
        get_adapter_for_session = AsyncMock()
        start_polling = AsyncMock()

        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute without exit marker
            result = await terminal_executor.execute_terminal_command(
                session_id="test-456",
                command="cd /home",
                session_manager=session_manager,
                config=config,
                get_adapter_for_session=get_adapter_for_session,
                start_polling=start_polling,
                append_exit_marker=False,
            )

            # Verify success
            assert result is True

            # Verify terminal_bridge.send_keys called with append_exit_marker=False
            mock_terminal.send_keys.assert_called_once_with(
                "test-tmux-2",
                "cd /home",
                shell="/bin/zsh",
                working_dir="/home",
                cols=120,
                rows=30,
                append_exit_marker=False,
            )

            # Verify activity updated
            session_manager.update_last_activity.assert_called_once_with("test-456")

            # Verify polling NOT started
            start_polling.assert_not_called()

    async def test_session_not_found(self):
        """Test error when session doesn't exist."""
        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=None)

        config = {"computer": {"default_shell": "/bin/bash"}}
        get_adapter_for_session = AsyncMock()
        start_polling = AsyncMock()

        # Execute
        result = await terminal_executor.execute_terminal_command(
            session_id="nonexistent",
            command="echo test",
            session_manager=session_manager,
            config=config,
            get_adapter_for_session=get_adapter_for_session,
            start_polling=start_polling,
        )

        # Verify failure
        assert result is False

        # Verify no further operations
        get_adapter_for_session.assert_not_called()
        start_polling.assert_not_called()

    async def test_terminal_send_keys_failure(self):
        """Test error handling when terminal.send_keys fails."""
        session_manager = Mock()
        session = Session(
            session_id="test-789",
            computer_name="TestMac",
            tmux_session_name="test-tmux-3",
            adapter_type="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()

        config = {"computer": {"default_shell": "/bin/bash"}}

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        start_polling = AsyncMock()

        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            # Simulate send_keys failure
            mock_terminal.send_keys = AsyncMock(return_value=False)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-789",
                command="invalid-command",
                session_manager=session_manager,
                config=config,
                get_adapter_for_session=get_adapter_for_session,
                start_polling=start_polling,
            )

            # Verify failure
            assert result is False

            # Verify error message sent to adapter
            adapter.send_message.assert_called_once_with(
                "test-789", "Failed to execute command: invalid-command"
            )

            # Verify no activity updates
            session_manager.update_last_activity.assert_not_called()

            # Verify no polling started
            start_polling.assert_not_called()

    async def test_terminal_size_parsing_default(self):
        """Test default terminal size when session.terminal_size is None."""
        session_manager = Mock()
        session = Session(
            session_id="test-default",
            computer_name="TestMac",
            tmux_session_name="test-tmux-default",
            adapter_type="telegram",
            title="Test",
            terminal_size=None,  # No terminal size
            working_directory="/tmp",
        )
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.cleanup_messages_after_success = AsyncMock()

        config = {"computer": {"default_shell": "/bin/bash"}}
        get_adapter_for_session = AsyncMock()
        start_polling = AsyncMock()

        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-default",
                command="echo test",
                session_manager=session_manager,
                config=config,
                get_adapter_for_session=get_adapter_for_session,
                start_polling=start_polling,
            )

            # Verify success
            assert result is True

            # Verify default size (80x24) used
            mock_terminal.send_keys.assert_called_once_with(
                "test-tmux-default",
                "echo test",
                shell="/bin/bash",
                working_dir="/tmp",
                cols=80,  # Default
                rows=24,  # Default
                append_exit_marker=True,
            )

    async def test_terminal_size_parsing_invalid(self):
        """Test fallback to default when terminal_size is invalid."""
        session_manager = Mock()
        session = Session(
            session_id="test-invalid",
            computer_name="TestMac",
            tmux_session_name="test-tmux-invalid",
            adapter_type="telegram",
            title="Test",
            terminal_size="invalid-size",  # Invalid format
            working_directory="/tmp",
        )
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_last_activity = AsyncMock()
        session_manager.cleanup_messages_after_success = AsyncMock()

        config = {"computer": {"default_shell": "/bin/bash"}}
        get_adapter_for_session = AsyncMock()
        start_polling = AsyncMock()

        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-invalid",
                command="echo test",
                session_manager=session_manager,
                config=config,
                get_adapter_for_session=get_adapter_for_session,
                start_polling=start_polling,
            )

            # Verify success
            assert result is True

            # Verify default size used (ValueError caught)
            mock_terminal.send_keys.assert_called_once_with(
                "test-tmux-invalid",
                "echo test",
                shell="/bin/bash",
                working_dir="/tmp",
                cols=80,  # Default fallback
                rows=24,  # Default fallback
                append_exit_marker=True,
            )
