"""Unit tests for polling_coordinator module."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.output_poller import IdleDetected, OutputChanged, ProcessExited


@pytest.mark.asyncio
class TestPollAndSendOutput:
    """Test poll_and_send_output function."""

    async def test_duplicate_polling_prevention(self):
        """Test polling request ignored when already polling."""
        session_manager = Mock()
        output_poller = Mock()
        get_adapter_for_session = AsyncMock()
        get_output_file = Mock()

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            # Already polling
            mock_state.is_polling = Mock(return_value=True)
            mock_state.mark_polling = Mock()

            # Execute
            await polling_coordinator.poll_and_send_output(
                "test-123",
                "test-tmux",
                session_manager,
                output_poller,
                get_adapter_for_session,
                get_output_file,
            )

            # Verify polling not started (adapter not called)
            get_adapter_for_session.assert_not_called()
            mock_state.mark_polling.assert_not_called()

    async def test_output_changed_event(self):
        """Test OutputChanged event handling."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.get_idle_notification_message_id = AsyncMock(return_value=None)
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to yield OutputChanged event
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(
                session_id="test-123",
                output="test output",
                started_at=1000.0,
                last_changed_at=1001.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=False)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            with patch("teleclaude.core.polling_coordinator.output_message_manager") as mock_output_mgr:
                mock_output_mgr.send_output_update = AsyncMock()

                # Execute
                await polling_coordinator.poll_and_send_output(
                    "test-123",
                    "test-tmux",
                    session_manager,
                    output_poller,
                    get_adapter_for_session,
                    get_output_file,
                )

                # Verify output update sent
                mock_output_mgr.send_output_update.assert_called_once_with(
                    "test-123",
                    adapter,
                    "test output",
                    1000.0,
                    1001.0,
                    session_manager,
                    max_message_length=3800,
                )

                # Verify cleanup
                mock_state.unmark_polling.assert_called_once_with("test-123")
                mock_state.remove_exit_marker.assert_called_once_with("test-123")

    async def test_output_changed_with_idle_notification_cleanup(self):
        """Test OutputChanged deletes idle notification if present."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.get_idle_notification_message_id = AsyncMock(return_value="idle-msg-456")
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        adapter.delete_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to yield OutputChanged event
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(
                session_id="test-123",
                output="resumed output",
                started_at=1000.0,
                last_changed_at=1002.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=False)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            with patch("teleclaude.core.polling_coordinator.output_message_manager") as mock_output_mgr:
                mock_output_mgr.send_output_update = AsyncMock()

                # Execute
                await polling_coordinator.poll_and_send_output(
                    "test-123",
                    "test-tmux",
                    session_manager,
                    output_poller,
                    get_adapter_for_session,
                    get_output_file,
                )

                # Verify idle notification deleted
                adapter.delete_message.assert_called_once_with("test-123", "idle-msg-456")
                session_manager.set_idle_notification_message_id.assert_called_with("test-123", None)

    async def test_idle_detected_event(self):
        """Test IdleDetected event handling."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock(return_value="idle-msg-789")
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to yield IdleDetected event
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield IdleDetected(session_id="test-123", idle_seconds=60)

        output_poller = Mock()
        output_poller.poll = mock_poll

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=False)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            # Execute
            await polling_coordinator.poll_and_send_output(
                "test-123",
                "test-tmux",
                session_manager,
                output_poller,
                get_adapter_for_session,
                get_output_file,
            )

            # Verify idle notification sent
            adapter.send_message.assert_called_once()
            call_args = adapter.send_message.call_args
            assert call_args[0][0] == "test-123"
            assert "60 seconds" in call_args[0][1]
            assert "⏸️" in call_args[0][1]

            # Verify notification ID persisted (called twice: once to set, once in finally to clear)
            assert session_manager.set_idle_notification_message_id.call_count == 2
            # First call sets the notification ID
            first_call = session_manager.set_idle_notification_message_id.call_args_list[0]
            assert first_call[0] == ("test-123", "idle-msg-789")

    async def test_process_exited_with_exit_code(self):
        """Test ProcessExited event with exit code."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_output_message_id = AsyncMock()
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to yield ProcessExited event with exit code
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield ProcessExited(
                session_id="test-123",
                final_output="command output",
                exit_code=0,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=True)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            with patch("teleclaude.core.polling_coordinator.output_message_manager") as mock_output_mgr:
                mock_output_mgr.send_output_update = AsyncMock()
                mock_output_mgr.send_exit_message = AsyncMock()

                with patch("teleclaude.core.polling_coordinator.time") as mock_time:
                    mock_time.time = Mock(return_value=1010.0)

                    # Execute
                    await polling_coordinator.poll_and_send_output(
                        "test-123",
                        "test-tmux",
                        session_manager,
                        output_poller,
                        get_adapter_for_session,
                        get_output_file,
                    )

                    # Verify final output sent with exit code
                    mock_output_mgr.send_output_update.assert_called_once_with(
                        "test-123",
                        adapter,
                        "command output",
                        1000.0,
                        1010.0,
                        session_manager,
                        max_message_length=3800,
                        is_final=True,
                        exit_code=0,
                    )

                    # Verify output message ID cleared
                    session_manager.set_output_message_id.assert_called_once_with("test-123", None)

                    # Verify send_exit_message NOT called (exit code path)
                    mock_output_mgr.send_exit_message.assert_not_called()

    async def test_process_exited_without_exit_code(self, tmp_path):
        """Test ProcessExited event without exit code (session died)."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_output_message_id = AsyncMock()
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        # Create real temp file
        output_file = tmp_path / "output.txt"
        output_file.write_text("test output")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to yield ProcessExited event without exit code
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield ProcessExited(
                session_id="test-123",
                final_output="partial output",
                exit_code=None,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=False)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            with patch("teleclaude.core.polling_coordinator.output_message_manager") as mock_output_mgr:
                mock_output_mgr.send_output_update = AsyncMock()
                mock_output_mgr.send_exit_message = AsyncMock()

                # Execute
                await polling_coordinator.poll_and_send_output(
                    "test-123",
                    "test-tmux",
                    session_manager,
                    output_poller,
                    get_adapter_for_session,
                    get_output_file,
                )

                # Verify exit message sent (not output update)
                mock_output_mgr.send_exit_message.assert_called_once_with(
                    "test-123",
                    adapter,
                    "partial output",
                    "✅ Process exited",
                    session_manager,
                )

                # Verify output file deleted
                assert not output_file.exists()

                # Verify output message ID cleared
                session_manager.set_output_message_id.assert_called_once_with("test-123", None)

                # Verify send_output_update NOT called (session died path)
                mock_output_mgr.send_output_update.assert_not_called()

    async def test_cleanup_in_finally_block(self):
        """Test cleanup always happens in finally block."""
        session_manager = Mock()
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to raise exception
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            raise RuntimeError("Polling error")
            yield  # Never reached

        output_poller = Mock()
        output_poller.poll = mock_poll

        with patch("teleclaude.core.polling_coordinator.state_manager") as mock_state:
            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=False)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            # Execute (exception raised)
            with pytest.raises(RuntimeError, match="Polling error"):
                await polling_coordinator.poll_and_send_output(
                    "test-123",
                    "test-tmux",
                    session_manager,
                    output_poller,
                    get_adapter_for_session,
                    get_output_file,
                )

            # Verify cleanup still happened
            mock_state.unmark_polling.assert_called_once_with("test-123")
            mock_state.remove_exit_marker.assert_called_once_with("test-123")
            session_manager.set_idle_notification_message_id.assert_called_once_with("test-123", None)
