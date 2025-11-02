"""Unit tests for simplified OutputPoller."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from teleclaude.core.output_poller import OutputPoller


@pytest.mark.unit
class TestOutputPoller:
    """Test OutputPoller core functionality."""

    @pytest.fixture
    def poller(self):
        """Create OutputPoller instance."""
        config = {"polling": {"idle_notification_seconds": 60}, "computer": {"timezone": "Europe/Amsterdam"}}
        terminal = Mock()
        session_manager = Mock()
        return OutputPoller(config, terminal, session_manager)

    def test_extract_exit_code_with_marker(self, poller):
        """Test exit code extraction when marker present."""
        output = "some output\n__EXIT__0__\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=True)
        assert exit_code == 0

        output = "error output\n__EXIT__1__\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=True)
        assert exit_code == 1

    def test_extract_exit_code_without_marker(self, poller):
        """Test exit code extraction when no marker."""
        output = "some output\n__EXIT__0__\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=False)
        assert exit_code is None

    def test_extract_exit_code_no_match(self, poller):
        """Test exit code when no marker in output."""
        output = "some output without marker\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=True)
        assert exit_code is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestMessageFormatting:
    """Test message formatting in all send methods."""

    @pytest.fixture
    def poller(self):
        """Create OutputPoller instance."""
        config = {"polling": {"idle_notification_seconds": 60}, "computer": {"timezone": "Europe/Amsterdam"}}
        terminal = Mock()
        session_manager = Mock()
        return OutputPoller(config, terminal, session_manager)

    async def test_send_exit_message_formatting(self, poller):
        """Test _send_exit_message formats output with backticks."""
        adapter = Mock()
        adapter.send_message = AsyncMock()
        adapter.edit_message = AsyncMock()

        output = "test output"
        exit_text = "✅ Process exited"

        # Call the method
        await poller._send_exit_message(adapter, "session-id", output, None, exit_text)

        # Verify send_message was called
        adapter.send_message.assert_called_once()

        # Get actual arguments
        args, kwargs = adapter.send_message.call_args
        session_id, message, metadata = args

        # Verify format: output in backticks, status line outside
        assert "```" in message
        assert "test output" in message
        assert exit_text in message
        # Status line should be after closing backticks
        assert message.index(exit_text) > message.rindex("```")

        # Verify metadata
        assert metadata["raw_format"] is True

    async def test_send_exit_message_empty_output(self, poller):
        """Test _send_exit_message with no output."""
        adapter = Mock()
        adapter.send_message = AsyncMock()

        exit_text = "✅ Process exited"

        await poller._send_exit_message(adapter, "session-id", "", None, exit_text)

        # Verify called
        adapter.send_message.assert_called_once()

        # Get message
        args, _ = adapter.send_message.call_args
        message = args[1]

        # With empty output, should still have exit text
        assert exit_text in message

    async def test_send_final_message_formatting(self, poller):
        """Test _send_final_message formats output with backticks."""
        adapter = Mock()
        adapter.send_message = AsyncMock()

        output = "command output"
        started_at = asyncio.get_event_loop().time()

        await poller._send_final_message(adapter, "session-id", output, None, 0, started_at, 3800)

        # Verify called
        adapter.send_message.assert_called_once()

        # Get arguments
        args, _ = adapter.send_message.call_args
        session_id, message, metadata = args

        # Verify format: output in backticks, status outside
        assert "```" in message
        assert "command output" in message
        assert "✅" in message  # Exit code 0

        # Status line should be after closing backticks
        assert message.rindex("✅") > message.rindex("```")

        # Verify metadata
        assert metadata["raw_format"] is True


@pytest.mark.unit
@pytest.mark.asyncio
class TestPollingFlow:
    """Test full polling flow."""

    @pytest.fixture
    def poller(self):
        """Create OutputPoller with mocked dependencies."""
        config = {"polling": {"idle_notification_seconds": 3}, "computer": {"timezone": "Europe/Amsterdam"}}
        terminal = Mock()
        terminal.session_exists = AsyncMock(return_value=True)
        terminal.capture_pane = AsyncMock(return_value="")
        session_manager = Mock()
        return OutputPoller(config, terminal, session_manager)

    async def test_session_death_detection(self, poller, tmp_path):
        """Test polling stops when session dies."""
        session_id = "test-session"
        output_file = tmp_path / f"{session_id[:8]}.txt"
        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-123")
        adapter.edit_message = AsyncMock()

        active_sessions = set()
        idle_notifications = {}
        exit_markers = {}

        # Session will die immediately
        poller.terminal.session_exists.return_value = False

        await poller.poll_and_send_output(
            session_id=session_id,
            tmux_session_name="test-tmux",
            adapter=adapter,
            output_dir=tmp_path,
            active_polling_sessions=active_sessions,
            long_running_sessions=set(),
            idle_notifications=idle_notifications,
            exit_marker_appended=exit_markers,
        )

        # Should have cleaned up
        assert session_id not in active_sessions
        assert not output_file.exists()  # Deleted on session death

        # Verify exit message format
        adapter.send_message.assert_called()
        args, _ = adapter.send_message.call_args
        message = args[1]
        metadata = args[2]

        # Should have formatted message
        assert "✅ Process exited" in message
        assert metadata["raw_format"] is True

    async def test_exit_code_detection(self, poller, tmp_path):
        """Test polling stops on exit code."""
        session_id = "test-session"
        output_file = tmp_path / f"{session_id[:8]}.txt"  # Matches actual filename
        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-123")
        adapter.edit_message = AsyncMock()

        active_sessions = set()
        idle_notifications = {}
        exit_markers = {session_id: True}

        # Return exit marker after initial delay
        call_count = 0

        async def mock_capture(_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "initial output"
            return "final output\n__EXIT__0__\n"

        poller.terminal.capture_pane.side_effect = mock_capture

        await poller.poll_and_send_output(
            session_id=session_id,
            tmux_session_name="test-tmux",
            adapter=adapter,
            output_dir=tmp_path,
            active_polling_sessions=active_sessions,
            long_running_sessions=set(),
            idle_notifications=idle_notifications,
            exit_marker_appended=exit_markers,
        )

        # Should have cleaned up
        assert session_id not in active_sessions
        assert output_file.exists()  # Kept for downloads
        assert "__EXIT__" not in output_file.read_text()  # Marker stripped

        # Verify final message format
        # Should have called send_message (initial) and edit_message (updates + final)
        assert adapter.send_message.called or adapter.edit_message.called

        # Get the last message (could be send or edit)
        if adapter.edit_message.called:
            args, _ = adapter.edit_message.call_args
            message = args[2]
            metadata = args[3]
        else:
            args, _ = adapter.send_message.call_args
            message = args[1]
            metadata = args[2]

        # Verify format: output in backticks, status outside
        assert "```" in message
        assert "final output" in message
        assert "✅" in message  # Exit code 0
        assert metadata["raw_format"] is True

    async def test_idle_notification(self, poller, tmp_path):
        """Test idle notification sent after threshold."""
        output_file = tmp_path / "test.txt"
        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-123")
        adapter.edit_message = AsyncMock()

        active_sessions = set()
        idle_notifications = {}
        exit_markers = {"test-session": True}

        # Return same output for threshold ticks, then exit
        call_count = 0

        async def mock_capture(_):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:  # Threshold is 3, 4th triggers notification
                return "static output"
            return "static output\n__EXIT__0__\n"

        poller.terminal.capture_pane.side_effect = mock_capture

        await poller.poll_and_send_output(
            session_id="test-session",
            tmux_session_name="test-tmux",
            adapter=adapter,
            output_dir=tmp_path,
            active_polling_sessions=active_sessions,
            long_running_sessions=set(),
            idle_notifications=idle_notifications,
            exit_marker_appended=exit_markers,
        )

        # Should have sent idle notification
        assert adapter.send_message.call_count >= 2  # At least: initial + idle notification + final
        calls = [str(call) for call in adapter.send_message.call_args_list]
        assert any("No output for" in str(call) for call in calls)
