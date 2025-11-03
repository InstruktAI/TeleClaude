"""Unit tests for simplified OutputPoller."""

from unittest.mock import AsyncMock, Mock

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
        started_at = 1234567890.0

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
