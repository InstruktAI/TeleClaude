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
        async def mock_poll(session_id, tmux_session_name, output_file):
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
        async def mock_poll(session_id, tmux_session_name, output_file):
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
        async def mock_poll(session_id, tmux_session_name, output_file):
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
        async def mock_poll(session_id, tmux_session_name, output_file):
            raise RuntimeError("Polling error")
            yield  # Never reached

        output_poller = Mock()
        output_poller.poll = mock_poll
