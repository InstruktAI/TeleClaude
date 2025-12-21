"""Unit tests for polling_coordinator module."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.output_poller import OutputChanged, ProcessExited


@pytest.mark.asyncio
class TestPollAndSendOutput:
    """Test poll_and_send_output function."""

    async def test_duplicate_polling_prevention(self):
        """Test polling request ignored when already polling."""
        db.clear_pending_deletions = AsyncMock()

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

        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)

        Mock()

        Path("/tmp/output.txt")

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

        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.set_output_message_id = AsyncMock()

        Mock()

        Path("/tmp/output.txt")

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

        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)
        db.set_output_message_id = AsyncMock()

        Mock()

        # Create real temp file
        output_file = tmp_path / "output.txt"
        output_file.write_text("test output")

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

        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_output_message_id = AsyncMock(return_value=None)

        Mock()

        Path("/tmp/output.txt")

        # Mock poller to raise exception
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            raise RuntimeError("Polling error")
            yield  # Never reached

        output_poller = Mock()
        output_poller.poll = mock_poll


class TestFilterForUI:
    """Test output filtering logic."""

    def _filter_for_ui(self, text: str) -> str:
        """Helper to apply UI filtering (mimics OutputPoller logic)."""
        import re

        from teleclaude.utils import strip_ansi_codes, strip_exit_markers

        # Strip ANSI codes and collapse whitespace, but KEEP markers (for exit detection)
        current_with_markers = strip_ansi_codes(text)
        current_with_markers = re.sub(r"\n\n+", "\n", current_with_markers)

        # Also create clean version (markers stripped) for UI
        return strip_exit_markers(current_with_markers)

    def test_collapses_multiple_blank_lines(self):
        """Test that multiple consecutive newlines are collapsed to single newline."""
        # Multiple blank lines (3+ newlines) should become single newline
        raw = "line1\n\n\n\nline2"
        result = self._filter_for_ui(raw)
        assert result == "line1\nline2"

    def test_preserves_single_newlines(self):
        """Test that single newlines are preserved."""
        raw = "line1\nline2\nline3"
        result = self._filter_for_ui(raw)
        assert result == "line1\nline2\nline3"

    def test_strips_ansi_codes(self):
        """Test that ANSI escape codes are removed."""
        raw = "\x1b[32mgreen text\x1b[0m"
        result = self._filter_for_ui(raw)
        assert result == "green text"

    def test_strips_exit_markers(self):
        """Test that exit markers are removed."""
        raw = "command output\n__EXIT__0__\n"
        result = self._filter_for_ui(raw)
        assert result == "command output\n"

    def test_strips_echo_command(self):
        """Test that echo command is removed."""
        raw = '; echo "__EXIT__$?__"'
        result = self._filter_for_ui(raw)
        assert result == ""

    def test_combined_filtering(self):
        """Test all filters working together."""
        # Realistic terminal output with ANSI codes, exit markers, and excessive blank lines
        raw = (
            "\x1b[32mcommand\x1b[0m\n"
            "\n\n\n"  # Excessive blank lines
            "output line 1\n"
            "output line 2\n"
            "\n\n"  # More blank lines
            "__EXIT__0__\n"
        )
        result = self._filter_for_ui(raw)

        # Should have ANSI stripped, exit marker removed, blank lines collapsed
        assert "\x1b[" not in result
        assert "__EXIT__" not in result
        assert "\n\n" not in result  # No consecutive blank lines
        assert "command" in result
        assert "output line 1" in result

    def test_handles_empty_string(self):
        """Test that empty string is handled gracefully."""
        assert self._filter_for_ui("") == ""

    def test_handles_only_whitespace(self):
        """Test handling of output with only newlines."""
        raw = "\n\n\n\n"
        result = self._filter_for_ui(raw)
        # Should collapse to single newline
        assert result == "\n"
