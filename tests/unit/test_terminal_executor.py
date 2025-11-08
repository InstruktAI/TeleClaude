"""Unit tests for terminal_executor module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import terminal_executor
from teleclaude.core.db import db
from teleclaude.core.models import Session


@pytest.mark.asyncio
class TestExecuteTerminalCommand:
    """Test execute_terminal_command function."""

    async def test_execute_success_with_exit_marker(self):
        """Test successful command execution with exit marker."""
        # Mock dependencies
        session = Session(
            session_id="test-123",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )
        db.get_session = AsyncMock(return_value=session)
        db.update_last_activity = AsyncMock()
        db.cleanup_messages_after_success = AsyncMock()

        client = Mock()
        client.delete_message = AsyncMock()
        start_polling = AsyncMock()

        # Mock terminal_bridge
        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-123",
                command="echo hello",
                client=client,
                start_polling=start_polling,
                append_exit_marker=True,
            )

            # Verify success
            assert result is True

            # Verify terminal_bridge.send_keys called with correct args
            # Verify send_keys was called (shell comes from config.computer.default_shell)
            assert mock_terminal.send_keys.called
            call_args = mock_terminal.send_keys.call_args
            assert call_args[0] == ("test-tmux", "echo hello")
            assert call_args[1]["working_dir"] == "/tmp"
            assert call_args[1]["cols"] == 80
            assert call_args[1]["rows"] == 24
            assert call_args[1]["append_exit_marker"] is True

            # Verify activity updated
            db.update_last_activity.assert_called_once_with("test-123")

            # Verify polling started
            start_polling.assert_called_once_with("test-123", "test-tmux")

    async def test_execute_success_without_exit_marker(self):
        """Test successful command execution without exit marker (no polling)."""
        session = Session(
            session_id="test-456",
            computer_name="TestMac",
            tmux_session_name="test-tmux-2",
            origin_adapter="telegram",
            title="Test",
            terminal_size="120x30",
            working_directory="/home",
        )
        db.get_session = AsyncMock(return_value=session)
        db.update_last_activity = AsyncMock()
        db.cleanup_messages_after_success = AsyncMock()

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
                
                client=client,
                
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
            db.update_last_activity.assert_called_once_with("test-456")

            # Verify polling NOT started
            start_polling.assert_not_called()

    async def test_session_not_found(self):
        """Test error when session doesn't exist."""
        db.get_session = AsyncMock(return_value=None)

        client = Mock()
        client.delete_message = AsyncMock()
        start_polling = AsyncMock()

        # Execute
        result = await terminal_executor.execute_terminal_command(
            session_id="nonexistent",
            command="echo test",
            
            client=client,
            
            start_polling=start_polling,
        )

        # Verify failure
        assert result is False

        # Verify no further operations
        get_adapter_for_session.assert_not_called()
        start_polling.assert_not_called()

    async def test_terminal_send_keys_failure(self):
        """Test error handling when terminal.send_keys fails."""
        session = Session(
            session_id="test-789",
            computer_name="TestMac",
            tmux_session_name="test-tmux-3",
            origin_adapter="telegram",
            title="Test",
            terminal_size="80x24",
            working_directory="/tmp",
        )
        db.get_session = AsyncMock(return_value=session)
        db.update_last_activity = AsyncMock()

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
                
                client=client,
                
                start_polling=start_polling,
            )

            # Verify failure
            assert result is False

            # Verify error message sent to adapter
            adapter.send_message.assert_called_once_with(
                "test-789", "Failed to execute command: invalid-command"
            )

            # Verify no activity updates
            db.update_last_activity.assert_not_called()

            # Verify no polling started
            start_polling.assert_not_called()

    async def test_terminal_size_parsing_default(self):
        """Test default terminal size when session.terminal_size is None."""
        session = Session(
            session_id="test-default",
            computer_name="TestMac",
            tmux_session_name="test-tmux-default",
            origin_adapter="telegram",
            title="Test",
            terminal_size=None,  # No terminal size
            working_directory="/tmp",
        )
        db.get_session = AsyncMock(return_value=session)
        db.update_last_activity = AsyncMock()
        db.cleanup_messages_after_success = AsyncMock()

        client = Mock()
        client.delete_message = AsyncMock()
        start_polling = AsyncMock()

        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-default",
                command="echo test",
                
                client=client,
                
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
        session = Session(
            session_id="test-invalid",
            computer_name="TestMac",
            tmux_session_name="test-tmux-invalid",
            origin_adapter="telegram",
            title="Test",
            terminal_size="invalid-size",  # Invalid format
            working_directory="/tmp",
        )
        db.get_session = AsyncMock(return_value=session)
        db.update_last_activity = AsyncMock()
        db.cleanup_messages_after_success = AsyncMock()

        client = Mock()
        client.delete_message = AsyncMock()
        start_polling = AsyncMock()

        with patch("teleclaude.core.terminal_executor.terminal_bridge") as mock_terminal:
            mock_terminal.send_keys = AsyncMock(return_value=True)
            mock_terminal.clear_history = AsyncMock(return_value=True)

            # Execute
            result = await terminal_executor.execute_terminal_command(
                session_id="test-invalid",
                command="echo test",
                
                client=client,
                
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
