"""Unit tests for file upload handler."""

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import file_handler
from teleclaude.core.events import FileEventContext
from teleclaude.core.models import (
    Session,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)


@pytest.fixture
def mock_session():
    """Create mock session."""
    return Session(
        session_id="test123",
        computer_name="test-computer",
        tmux_session_name="tmux_test123",
        origin_adapter="telegram",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=456, output_message_id="msg_123")
        ),
        title="Test Session",
        closed=False,
    )


@pytest.fixture
def mock_ux_state():
    """Create mock UX state."""
    state = MagicMock()
    state.output_message_id = "msg_123"
    return state


class TestSanitizeFilename:
    """Test filename sanitization."""

    def test_removes_special_characters(self):
        """Test that special characters are replaced with underscores."""
        assert file_handler.sanitize_filename('file<>:"/|?*.txt') == "file________.txt"

    def test_preserves_valid_characters(self):
        """Test that valid characters are preserved."""
        assert file_handler.sanitize_filename("my-file_123.pdf") == "my-file_123.pdf"

    def test_strips_leading_trailing_dots(self):
        """Test that leading/trailing dots are stripped."""
        assert file_handler.sanitize_filename("..file...") == "file"

    def test_handles_empty_result(self):
        """Test that empty filenames return 'file'."""
        assert file_handler.sanitize_filename("...") == "file"
        assert file_handler.sanitize_filename("") == "file"


class TestIsClaudeCodeRunning:
    """Test Claude Code detection."""

    @pytest.mark.asyncio
    async def test_detects_claude_in_title(self):
        """Test detection when 'claude' is in pane title."""
        with patch("teleclaude.core.file_handler.terminal_bridge.get_pane_title", return_value="claude"):
            result = await file_handler.is_claude_code_running("test_session")
            assert result is True

    @pytest.mark.asyncio
    async def test_detects_claude_case_insensitive(self):
        """Test case-insensitive detection."""
        with patch("teleclaude.core.file_handler.terminal_bridge.get_pane_title", return_value="Running Claude Code"):
            result = await file_handler.is_claude_code_running("test_session")
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_other_process(self):
        """Test returns False when Claude not detected."""
        with patch("teleclaude.core.file_handler.terminal_bridge.get_pane_title", return_value="vim"):
            result = await file_handler.is_claude_code_running("test_session")
            assert result is False

    @pytest.mark.asyncio
    async def test_handles_none_title(self):
        """Test handles None return from get_pane_title."""
        with patch("teleclaude.core.file_handler.terminal_bridge.get_pane_title", return_value=None):
            result = await file_handler.is_claude_code_running("test_session")
            assert result is False

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        """Test handles exception from terminal_bridge."""
        with patch("teleclaude.core.file_handler.terminal_bridge.get_pane_title", side_effect=Exception("tmux error")):
            result = await file_handler.is_claude_code_running("test_session")
            assert result is False


class TestHandleFile:
    """Test main file handling logic."""

    @pytest.mark.asyncio
    async def test_rejects_when_session_not_found(self, mock_ux_state):
        """Test rejection when session doesn't exist."""
        sent_messages = []

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_id"

        with patch("teleclaude.core.file_handler.db.get_session", return_value=None):
            await file_handler.handle_file(
                session_id="nonexistent",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="nonexistent", file_path="/tmp/file.pdf", filename="file.pdf"),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_messages) == 0

    @pytest.mark.asyncio
    async def test_rejects_when_no_process_running(self, mock_session, mock_ux_state):
        """Test rejection when no process is active."""
        sent_messages = []

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_id"

        with (
            patch("teleclaude.core.file_handler.db.get_session", return_value=mock_session),
            patch("teleclaude.core.file_handler.db.is_polling", return_value=False),
        ):
            await file_handler.handle_file(
                session_id="test123",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="test123", file_path="/tmp/file.pdf", filename="file.pdf"),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_messages) == 1
        assert "requires an active process" in sent_messages[0][1]

    @pytest.mark.asyncio
    async def test_rejects_when_no_output_message(self):
        """Test rejection when output message not ready."""
        sent_messages = []

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_id"

        # Create session WITHOUT output_message_id
        session_no_output = Session(
            session_id="test123",
            computer_name="test-computer",
            tmux_session_name="tmux_test123",
            origin_adapter="telegram",
            adapter_metadata=SessionAdapterMetadata(
                telegram=TelegramAdapterMetadata(topic_id=456)  # No output_message_id
            ),
            title="Test Session",
            closed=False,
        )

        with (
            patch("teleclaude.core.file_handler.db.get_session", return_value=session_no_output),
            patch("teleclaude.core.file_handler.db.is_polling", return_value=True),
            patch("teleclaude.core.file_handler.db.update_last_activity"),
        ):
            await file_handler.handle_file(
                session_id="test123",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="test123", file_path="/tmp/file.pdf", filename="file.pdf"),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_messages) == 1
        assert "not ready yet" in sent_messages[0][1]

    @pytest.mark.asyncio
    async def test_sends_at_prefix_for_claude_code(self, mock_session, mock_ux_state):
        """Test @ prefix is added for Claude Code."""
        sent_keys = []

        async def mock_send_keys(session_name: str, text: str) -> tuple[bool, Optional[str]]:
            sent_keys.append((session_name, text))
            return (True, "marker123")

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            return "msg_id"

        with (
            patch("teleclaude.core.file_handler.db.get_session", return_value=mock_session),
            patch("teleclaude.core.file_handler.db.is_polling", return_value=True),
            patch("teleclaude.core.file_handler.db.get_ux_state", return_value=mock_ux_state),
            patch("teleclaude.core.file_handler.is_claude_code_running", return_value=True),
            patch("teleclaude.core.file_handler.terminal_bridge.send_keys", side_effect=mock_send_keys),
            patch("teleclaude.core.file_handler.db.update_last_activity"),
        ):
            await file_handler.handle_file(
                session_id="test123",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="test123", file_path="/tmp/file.pdf", filename="file.pdf", file_size=1024),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_keys) == 1
        # Path.resolve() converts to absolute path (e.g., /tmp -> /private/tmp on macOS)
        expected_path = str(Path("/tmp/file.pdf").resolve())
        assert sent_keys[0][1] == f"@{expected_path}"

    @pytest.mark.asyncio
    async def test_sends_plain_path_for_other_process(self, mock_session, mock_ux_state):
        """Test plain path is sent for non-Claude processes."""
        sent_keys = []

        async def mock_send_keys(session_name: str, text: str) -> tuple[bool, Optional[str]]:
            sent_keys.append((session_name, text))
            return (True, "marker123")

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            return "msg_id"

        with (
            patch("teleclaude.core.file_handler.db.get_session", return_value=mock_session),
            patch("teleclaude.core.file_handler.db.is_polling", return_value=True),
            patch("teleclaude.core.file_handler.db.get_ux_state", return_value=mock_ux_state),
            patch("teleclaude.core.file_handler.is_claude_code_running", return_value=False),
            patch("teleclaude.core.file_handler.terminal_bridge.send_keys", side_effect=mock_send_keys),
            patch("teleclaude.core.file_handler.db.update_last_activity"),
        ):
            await file_handler.handle_file(
                session_id="test123",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="test123", file_path="/tmp/file.pdf", filename="file.pdf", file_size=1024),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_keys) == 1
        # Path.resolve() converts to absolute path (e.g., /tmp -> /private/tmp on macOS)
        expected_path = str(Path("/tmp/file.pdf").resolve())
        assert sent_keys[0][1] == expected_path

    @pytest.mark.asyncio
    async def test_sends_confirmation_with_file_size(self, mock_session, mock_ux_state):
        """Test confirmation message includes file size."""
        sent_messages = []

        async def mock_send_keys(session_name: str, text: str) -> tuple[bool, Optional[str]]:
            return (True, "marker123")

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_id"

        with (
            patch("teleclaude.core.file_handler.db.get_session", return_value=mock_session),
            patch("teleclaude.core.file_handler.db.is_polling", return_value=True),
            patch("teleclaude.core.file_handler.db.get_ux_state", return_value=mock_ux_state),
            patch("teleclaude.core.file_handler.is_claude_code_running", return_value=True),
            patch("teleclaude.core.file_handler.terminal_bridge.send_keys", side_effect=mock_send_keys),
            patch("teleclaude.core.file_handler.db.update_last_activity"),
        ):
            await file_handler.handle_file(
                session_id="test123",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="test123", file_path="/tmp/file.pdf", filename="file.pdf", file_size=2097152),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_messages) == 1
        assert "file.pdf" in sent_messages[0][1]
        assert "2.00 MB" in sent_messages[0][1]

    @pytest.mark.asyncio
    async def test_handles_send_keys_failure(self, mock_session, mock_ux_state):
        """Test error handling when send_keys fails."""
        sent_messages = []

        async def mock_send_keys(session_name: str, text: str) -> tuple[bool, Optional[str]]:
            return (False, None)

        async def mock_send_feedback(sid: str, msg: str, metadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_id"

        with (
            patch("teleclaude.core.file_handler.db.get_session", return_value=mock_session),
            patch("teleclaude.core.file_handler.db.is_polling", return_value=True),
            patch("teleclaude.core.file_handler.db.get_ux_state", return_value=mock_ux_state),
            patch("teleclaude.core.file_handler.is_claude_code_running", return_value=True),
            patch("teleclaude.core.file_handler.terminal_bridge.send_keys", side_effect=mock_send_keys),
        ):
            await file_handler.handle_file(
                session_id="test123",
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(session_id="test123", file_path="/tmp/file.pdf", filename="file.pdf"),
                send_feedback=mock_send_feedback,
            )

        assert len(sent_messages) == 1
        assert "Failed to send" in sent_messages[0][1]
