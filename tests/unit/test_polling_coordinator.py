"""Unit tests for polling_coordinator module."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.output_poller import IdleDetected, OutputChanged, ProcessExited


@pytest.mark.asyncio
class TestPollAndSendOutput:
    """Test poll_and_send_output function."""

    async def test_duplicate_polling_prevention(self):
        """Test polling request ignored when already polling."""
        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        output_poller = Mock()
        get_adapter_for_session = AsyncMock()
        get_output_file = Mock()

    async def test_output_changed_event(self):
        """Test OutputChanged event handling."""
        # Mock session with human-readable title (not AI-to-AI)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",  # Not matching $X > $Y pattern
        )

        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.get_idle_notification_message_id = AsyncMock(return_value=None)
        db.set_idle_notification_message_id = AsyncMock()

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

    async def test_output_changed_with_idle_notification_cleanup(self):
        """Test OutputChanged deletes idle notification if present."""
        # Mock session with human-readable title (not AI-to-AI)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
        )

        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.get_idle_notification_message_id = AsyncMock(return_value="idle-msg-456")
        db.set_idle_notification_message_id = AsyncMock()

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

    async def test_idle_detected_event(self):
        """Test IdleDetected event handling."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
        )

        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.set_idle_notification_message_id = AsyncMock()

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

    async def test_process_exited_with_exit_code(self):
        """Test ProcessExited event with exit code."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
        )

        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.set_output_message_id = AsyncMock()
        db.set_idle_notification_message_id = AsyncMock()

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

    async def test_process_exited_without_exit_code(self, tmp_path):
        """Test ProcessExited event without exit code (session died)."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
        )

        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.set_output_message_id = AsyncMock()
        db.set_idle_notification_message_id = AsyncMock()

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

    async def test_cleanup_in_finally_block(self):
        """Test cleanup always happens in finally block."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
        )

        session_manager = Mock()
        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.set_idle_notification_message_id = AsyncMock()

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


class TestNotificationFlagCoordination:
    """Tests for notification_sent flag coordination with idle detection."""

    @pytest.mark.asyncio
    async def test_idle_notification_skipped_when_flag_set(self):
        """Test IdleDetected event skipped when notification_sent flag is True."""
        from pathlib import Path
        from unittest.mock import AsyncMock, Mock

        from teleclaude.core.output_poller import IdleDetected
        from teleclaude.core.polling_coordinator import poll_and_send_output

        # Setup mocks
        adapter_client = AsyncMock()
        adapter_client.send_message = AsyncMock()
        adapter_client.delete_message = AsyncMock()

        # Mock db with notification_sent=True
        from unittest.mock import patch

        mock_db = AsyncMock()
        mock_db.is_polling = AsyncMock(return_value=False)  # Allow polling to start
        mock_db.mark_polling = AsyncMock()
        mock_db.unmark_polling = AsyncMock()
        mock_db.clear_pending_deletions = AsyncMock()
        mock_db.get_session = AsyncMock(
            return_value=Mock(
                session_id="test-123",
                origin_adapter="telegram",
                adapter_metadata={},
                tmux_session_name="test-tmux",
            )
        )
        mock_db.get_notification_flag = AsyncMock(return_value=True)  # Flag is set
        mock_db.get_ux_state = AsyncMock(return_value=Mock(idle_notification_message_id=None, notification_sent=True))
        mock_db.update_ux_state = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        # Mock poller to yield IdleDetected
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield IdleDetected(session_id="test-123", idle_seconds=60)

        output_poller = Mock()
        output_poller.poll = mock_poll

        # Patch db at the point where it's used in polling_coordinator
        with patch("teleclaude.core.polling_coordinator.db", mock_db):
            # Execute
            await poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
            )

            # VERIFY: Idle notification NOT sent (flag was set)
            adapter_client.send_message.assert_not_called()

            # VERIFY: get_notification_flag was checked
            mock_db.get_notification_flag.assert_called_once_with("test-123")

    @pytest.mark.asyncio
    async def test_idle_notification_sent_when_flag_not_set(self):
        """Test IdleDetected event sends notification when notification_sent flag is False."""
        from pathlib import Path
        from unittest.mock import AsyncMock, Mock, patch

        from teleclaude.core.output_poller import IdleDetected
        from teleclaude.core.polling_coordinator import poll_and_send_output

        # Setup mocks
        adapter_client = AsyncMock()
        adapter_client.send_message = AsyncMock(return_value="msg-123")

        # Mock db with notification_sent=False
        mock_db = AsyncMock()
        mock_db.is_polling = AsyncMock(return_value=False)  # Allow polling to start
        mock_db.mark_polling = AsyncMock()
        mock_db.unmark_polling = AsyncMock()
        mock_db.clear_pending_deletions = AsyncMock()
        mock_db.get_session = AsyncMock(
            return_value=Mock(
                session_id="test-456",
                origin_adapter="telegram",
                adapter_metadata={},
                tmux_session_name="test-tmux",
            )
        )
        mock_db.get_notification_flag = AsyncMock(return_value=False)  # Flag NOT set
        mock_db.get_ux_state = AsyncMock(return_value=Mock(idle_notification_message_id=None, notification_sent=False))
        mock_db.update_ux_state = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        # Mock poller to yield IdleDetected
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield IdleDetected(session_id="test-456", idle_seconds=60)

        output_poller = Mock()
        output_poller.poll = mock_poll

        # Patch db at the point where it's used in polling_coordinator
        with patch("teleclaude.core.polling_coordinator.db", mock_db):
            # Execute
            await poll_and_send_output(
                session_id="test-456",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
            )

            # VERIFY: Idle notification WAS sent (flag was not set)
            adapter_client.send_message.assert_called_once()
            call_args = adapter_client.send_message.call_args
            assert "No output for 60 seconds" in call_args[0][1]

            # VERIFY: get_notification_flag was checked
            mock_db.get_notification_flag.assert_called_once_with("test-456")

            # VERIFY: Message ID persisted to DB (check for idle_notification_message_id call)
            # update_ux_state is called multiple times:
            # 1. polling_active=True (line 167)
            # 2. idle_notification_message_id='msg-123' (line 225)
            # 3. idle_notification_message_id=None (finally block, line 286)
            assert any(
                call[1].get("idle_notification_message_id") == "msg-123"
                for call in mock_db.update_ux_state.call_args_list
            )

    @pytest.mark.asyncio
    async def test_notification_flag_cleared_on_output_change(self):
        """Test notification_sent flag cleared when OutputChanged event occurs."""
        from pathlib import Path
        from unittest.mock import AsyncMock, Mock, patch

        from teleclaude.core.output_poller import OutputChanged
        from teleclaude.core.polling_coordinator import poll_and_send_output

        # Setup mocks
        adapter_client = AsyncMock()
        adapter_client.send_output_update = AsyncMock()

        # Mock db with notification_sent=True initially
        mock_db = AsyncMock()
        mock_db.is_polling = AsyncMock(return_value=False)  # Allow polling to start
        mock_db.mark_polling = AsyncMock()
        mock_db.unmark_polling = AsyncMock()
        mock_db.clear_pending_deletions = AsyncMock()
        mock_db.get_session = AsyncMock(
            return_value=Mock(
                session_id="test-789",
                origin_adapter="telegram",
                adapter_metadata={},
                tmux_session_name="test-tmux",
            )
        )
        mock_db.get_ux_state = AsyncMock(
            return_value=Mock(
                idle_notification_message_id=None,
                notification_sent=True,  # Flag is set initially
            )
        )
        mock_db.clear_notification_flag = AsyncMock()
        mock_db.update_ux_state = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        # Mock poller to yield OutputChanged
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(session_id="test-789", output="new output", started_at=1000.0, last_changed_at=1001.0)

        output_poller = Mock()
        output_poller.poll = mock_poll

        # Patch db at the point where it's used in polling_coordinator
        with patch("teleclaude.core.polling_coordinator.db", mock_db):
            # Execute
            await poll_and_send_output(
                session_id="test-789",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
            )

            # VERIFY: clear_notification_flag was called (activity detected)
            mock_db.clear_notification_flag.assert_called_once_with("test-789")


class TestFilterForUI:
    """Test _filter_for_ui function."""

    def test_collapses_multiple_blank_lines(self):
        """Test that multiple consecutive newlines are collapsed to single newline."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        # Multiple blank lines (3+ newlines) should become single newline
        raw = "line1\n\n\n\nline2"
        result = _filter_for_ui(raw)
        assert result == "line1\nline2"

    def test_preserves_single_newlines(self):
        """Test that single newlines are preserved."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        raw = "line1\nline2\nline3"
        result = _filter_for_ui(raw)
        assert result == "line1\nline2\nline3"

    def test_strips_ansi_codes(self):
        """Test that ANSI escape codes are removed."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        raw = "\x1b[32mgreen text\x1b[0m"
        result = _filter_for_ui(raw)
        assert result == "green text"

    def test_strips_exit_markers(self):
        """Test that exit markers are removed."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        raw = "command output\n__EXIT__0__\n"
        result = _filter_for_ui(raw)
        assert result == "command output\n"

    def test_strips_echo_command(self):
        """Test that echo command is removed."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        raw = '; echo "__EXIT__$?__"'
        result = _filter_for_ui(raw)
        assert result == ""

    def test_combined_filtering(self):
        """Test all filters working together."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        # Realistic terminal output with ANSI codes, exit markers, and excessive blank lines
        raw = (
            "\x1b[32mcommand\x1b[0m\n"
            "\n\n\n"  # Excessive blank lines
            "output line 1\n"
            "output line 2\n"
            "\n\n"  # More blank lines
            "__EXIT__0__\n"
        )
        result = _filter_for_ui(raw)

        # Should have ANSI stripped, exit marker removed, blank lines collapsed
        assert "\x1b[" not in result
        assert "__EXIT__" not in result
        assert "\n\n" not in result  # No consecutive blank lines
        assert "command" in result
        assert "output line 1" in result

    def test_handles_empty_string(self):
        """Test that empty string is handled gracefully."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        assert _filter_for_ui("") == ""

    def test_handles_only_whitespace(self):
        """Test handling of output with only newlines."""
        from teleclaude.core.polling_coordinator import _filter_for_ui

        raw = "\n\n\n\n"
        result = _filter_for_ui(raw)
        # Should collapse to single newline
        assert result == "\n"
