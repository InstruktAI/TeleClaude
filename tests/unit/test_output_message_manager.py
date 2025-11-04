"""Unit tests for output_message_manager module."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import output_message_manager


@pytest.mark.asyncio
class TestSendStatusMessage:
    """Test send_status_message function."""

    async def test_send_new_message(self):
        """Test sending new status message (append=False)."""
        session_manager = Mock()
        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-123")

        # Execute
        result = await output_message_manager.send_status_message(
            "test-session",
            adapter,
            "Processing...",
            session_manager,
            append_to_existing=False,
        )

        # Verify
        adapter.send_message.assert_called_once_with("test-session", "Processing...")
        assert result == "msg-123"

    async def test_append_to_existing_message(self, tmp_path):
        """Test appending to existing message."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-456")

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=True)

        # Create output file
        output_file = tmp_path / "output.txt"
        output_file.write_text("existing output")

        # Execute
        result = await output_message_manager.send_status_message(
            "test-session",
            adapter,
            "Status update",
            session_manager,
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        # Verify edit called
        adapter.edit_message.assert_called_once()
        assert result == "msg-456"

    async def test_append_fails_without_message_id(self):
        """Test append fails when no message_id."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)

        adapter = Mock()

        # Execute
        result = await output_message_manager.send_status_message(
            "test-session",
            adapter,
            "Status",
            session_manager,
            append_to_existing=True,
            output_file_path="/tmp/output.txt",
        )

        # Verify no message sent, returns None
        assert result is None

    async def test_append_fails_without_output_file(self):
        """Test append fails when no output_file_path."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-789")

        adapter = Mock()

        # Execute
        result = await output_message_manager.send_status_message(
            "test-session",
            adapter,
            "Status",
            session_manager,
            append_to_existing=True,
            output_file_path=None,
        )

        # Verify no message sent, returns None
        assert result is None

    async def test_append_edit_fails_sends_new_message(self, tmp_path):
        """Test append falls back to new message when edit fails."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-stale")
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=False)  # Edit fails
        adapter.send_message = AsyncMock(return_value="msg-new")

        # Create output file
        output_file = tmp_path / "output.txt"
        output_file.write_text("existing output")

        # Execute
        result = await output_message_manager.send_status_message(
            "test-session",
            adapter,
            "Status",
            session_manager,
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        # Verify edit attempted
        adapter.edit_message.assert_called_once()

        # Verify stale message_id cleared
        session_manager.set_output_message_id.assert_called_once_with("test-session", None)

        # Verify new message sent
        adapter.send_message.assert_called_once()
        assert result == "msg-new"


@pytest.mark.asyncio
class TestSendOutputUpdate:
    """Test send_output_update function."""

    async def test_send_new_message(self):
        """Test sending new output message."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-123")

        with patch("teleclaude.core.output_message_manager.get_config") as mock_config:
            mock_config.return_value = {"computer": {"timezone": "UTC"}}

            # Execute
            result = await output_message_manager.send_output_update(
                "test-session",
                adapter,
                "test output",
                1000.0,
                1001.0,
                session_manager,
            )

            # Verify new message sent
            adapter.send_message.assert_called_once()
            session_manager.set_output_message_id.assert_called_once_with("test-session", "msg-123")
            assert result == "msg-123"

    async def test_edit_existing_message(self):
        """Test editing existing output message."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-456")

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=True)

        with patch("teleclaude.core.output_message_manager.get_config") as mock_config:
            mock_config.return_value = {"computer": {"timezone": "UTC"}}

            # Execute
            result = await output_message_manager.send_output_update(
                "test-session",
                adapter,
                "updated output",
                1000.0,
                1002.0,
                session_manager,
            )

            # Verify edit called
            adapter.edit_message.assert_called_once()
            assert result == "msg-456"

    async def test_edit_fails_sends_new_message(self):
        """Test fallback to new message when edit fails."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-stale")
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=False)  # Edit fails
        adapter.send_message = AsyncMock(return_value="msg-new")

        with patch("teleclaude.core.output_message_manager.get_config") as mock_config:
            mock_config.return_value = {"computer": {"timezone": "UTC"}}

            # Execute
            result = await output_message_manager.send_output_update(
                "test-session",
                adapter,
                "output",
                1000.0,
                1001.0,
                session_manager,
            )

            # Verify edit attempted
            adapter.edit_message.assert_called_once()

            # Verify stale message_id cleared
            assert session_manager.set_output_message_id.call_count == 2
            first_call = session_manager.set_output_message_id.call_args_list[0]
            assert first_call[0] == ("test-session", None)

            # Verify new message sent
            adapter.send_message.assert_called_once()
            assert result == "msg-new"

    async def test_truncation_when_output_exceeds_max_length(self):
        """Test output truncation and download button."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-789")

        # Create long output
        long_output = "x" * 5000

        with patch("teleclaude.core.output_message_manager.get_config") as mock_config:
            mock_config.return_value = {"computer": {"timezone": "UTC"}}

            # Execute
            result = await output_message_manager.send_output_update(
                "test-session",
                adapter,
                long_output,
                1000.0,
                1001.0,
                session_manager,
                max_message_length=3800,
            )

            # Verify message sent with metadata including reply_markup (download button)
            adapter.send_message.assert_called_once()
            call_args = adapter.send_message.call_args
            metadata = call_args[0][2]  # Third argument is metadata
            assert "reply_markup" in metadata
            assert result == "msg-789"

    async def test_final_message_with_exit_code(self):
        """Test final message with exit code."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-existing")

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=True)

        with patch("teleclaude.core.output_message_manager.get_config") as mock_config:
            mock_config.return_value = {"computer": {"timezone": "UTC"}}

            # Execute
            result = await output_message_manager.send_output_update(
                "test-session",
                adapter,
                "final output",
                1000.0,
                1010.0,
                session_manager,
                is_final=True,
                exit_code=0,
            )

            # Verify edit called with final status
            adapter.edit_message.assert_called_once()
            assert result == "msg-existing"

    async def test_status_color_based_on_idle_time(self):
        """Test status color changes based on idle time."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-123")

        with patch("teleclaude.core.output_message_manager.get_config") as mock_config:
            mock_config.return_value = {"computer": {"timezone": "UTC"}}

            with patch("teleclaude.core.output_message_manager.time") as mock_time:
                current_time = 1100.0
                mock_time.time = Mock(return_value=current_time)

                # Test different idle times
                test_cases = [
                    (1098.0, "⚪"),  # 2 seconds idle (≤5)
                    (1092.0, "🟡"),  # 8 seconds idle (≤10)
                    (1085.0, "🟠"),  # 15 seconds idle (≤20)
                    (1070.0, "🔴"),  # 30 seconds idle (>20)
                ]

                for last_changed_at, expected_color in test_cases:
                    adapter.send_message.reset_mock()

                    # Execute
                    await output_message_manager.send_output_update(
                        "test-session",
                        adapter,
                        "output",
                        1000.0,
                        last_changed_at,
                        session_manager,
                    )

                    # Verify message sent with correct color in status line
                    adapter.send_message.assert_called_once()
                    call_args = adapter.send_message.call_args
                    message_text = call_args[0][1]  # Second argument is message text
                    assert expected_color in message_text


@pytest.mark.asyncio
class TestSendExitMessage:
    """Test send_exit_message function."""

    async def test_edit_existing_message(self):
        """Test editing existing message with exit text."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-456")
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=True)

        # Execute
        await output_message_manager.send_exit_message(
            "test-session",
            adapter,
            "final output",
            "✅ Process exited",
            session_manager,
        )

        # Verify edit called
        adapter.edit_message.assert_called_once()

        # Verify message_id cleared
        session_manager.set_output_message_id.assert_called_once_with("test-session", None)

    async def test_edit_fails_sends_new_message(self):
        """Test sending new message when edit fails."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value="msg-stale")
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.edit_message = AsyncMock(return_value=False)  # Edit fails
        adapter.send_message = AsyncMock(return_value="msg-new")

        # Execute
        await output_message_manager.send_exit_message(
            "test-session",
            adapter,
            "final output",
            "✅ Process exited",
            session_manager,
        )

        # Verify edit attempted
        adapter.edit_message.assert_called_once()

        # Verify new message sent
        adapter.send_message.assert_called_once()

        # Verify message_id cleared
        session_manager.set_output_message_id.assert_called_once_with("test-session", None)

    async def test_no_existing_message_sends_new(self):
        """Test sending new message when no existing message."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_output_message_id = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="msg-new")

        # Execute
        await output_message_manager.send_exit_message(
            "test-session",
            adapter,
            "output",
            "✅ Process exited",
            session_manager,
        )

        # Verify new message sent (edit not called)
        adapter.send_message.assert_called_once()

        # Verify message_id cleared
        session_manager.set_output_message_id.assert_called_once_with("test-session", None)
