"""Integration tests for voice transcription status appending during active polling."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import db, Db


class TestUiAdapter(UiAdapter):
    """Test implementation of UiAdapter for testing."""

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(self, session_id: str, text: str, metadata=None) -> str:
        # Mock implementation
        return self._mock_send_message(session_id, text, metadata)

    async def edit_message(self, session_id: str, message_id: str, text: str) -> bool:
        # Mock implementation
        return self._mock_edit_message(session_id, message_id, text)

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        # Mock implementation
        return True

    async def create_channel(self, session_id: str, title: str, metadata: dict) -> str:
        return "test-channel"

    async def update_channel_title(self, session_id: str, title: str) -> bool:
        return True

    async def delete_channel(self, session_id: str) -> bool:
        return True

    async def send_general_message(self, text: str, metadata=None) -> str:
        return "msg-general"

    async def discover_peers(self):
        return []


@pytest.mark.integration
@pytest.mark.asyncio
class TestVoiceStatusAppend:
    """Test voice transcription status appending to active process output."""

    @pytest.fixture
    async def session_manager(self, tmp_path):
        """Create Db with temp database."""
        db_path = str(tmp_path / "test.db")
        session_mgr = Db(db_path)
        await session_mgr.initialize()
        yield session_mgr
        await session_mgr.close()

    async def test_append_status_to_existing_output(self, session_manager, tmp_path):
        """Test that status message appends to existing output during active polling."""
        # Create session first (required for message_id storage)
        session = await db.create_session(
            computer_name="TestComputer",
            tmux_session_name="test-voice-tmux",
            origin_adapter="telegram",
            adapter_metadata={"chat_id": "123", "topic_id": "456"},
        )
        session_id = session.session_id

        # Create output file with existing process output
        output_file = tmp_path / f"{session_id[:8]}.txt"
        existing_output = "Running process...\nsome output here"
        output_file.write_text(existing_output)

        # Create test adapter with mocked methods
        adapter = TestUiAdapter(None)
        adapter._mock_edit_message = AsyncMock(return_value=True)
        adapter._mock_send_message = AsyncMock(return_value="msg-123")

        # Set message ID (simulating active polling)
        await db.update_ux_state(session_id, output_message_id="msg-123")

        # Send status message with append_to_existing=True
        result = await adapter.send_status_message(
            session_id=session_id,
            text="🎤 Transcribing...",
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        # Should return the same message ID
        assert result == "msg-123"

        # Verify adapter.edit_message was called
        adapter._mock_edit_message.assert_called_once()
        args, kwargs = adapter._mock_edit_message.call_args

        # Check arguments
        assert args[0] == session_id  # session_id
        assert args[1] == "msg-123"  # message_id

        # Check formatted message (status should be OUTSIDE code block)
        formatted_message = args[2]
        assert "```" in formatted_message
        assert "🎤 Transcribing..." in formatted_message

        # Verify status is outside code block (not between backticks)
        # Format should be: ```\noutput\n```\n🎤 Transcribing...
        assert formatted_message.index("🎤 Transcribing...") > formatted_message.rindex("```")

        # Verify output is in the formatted message
        assert "Running process" in formatted_message
        assert "some output here" in formatted_message

    async def test_send_new_message_when_no_active_polling(self, session_manager, tmp_path):
        """Test that status sends new message when append_to_existing=False.

        Note: In the daemon, voice messages are REJECTED if no active process.
        This test verifies UiAdapter can send standalone status messages.
        """
        session_id = "test-session-456"

        # Create test adapter
        adapter = TestUiAdapter(None)
        adapter._mock_send_message = AsyncMock(return_value="msg-new")

        # Send status message with append_to_existing=False
        result = await adapter.send_status_message(
            session_id=session_id,
            text="🎤 Transcribing...",
            append_to_existing=False,
        )

        # Should return new message ID
        assert result == "msg-new"

        # Verify adapter.send_message was called
        adapter._mock_send_message.assert_called_once_with(session_id, "🎤 Transcribing...", None)

    async def test_append_without_message_id_sends_new(self, session_manager, tmp_path):
        """Test that append without message_id returns None (can't append)."""
        session_id = "test-session-789"
        output_file = tmp_path / f"{session_id[:8]}.txt"
        output_file.write_text("some output")

        # Create test adapter
        adapter = TestUiAdapter(None)
        adapter._mock_send_message = AsyncMock(return_value="msg-new")

        # No message ID set but trying to append
        result = await adapter.send_status_message(
            session_id=session_id,
            text="🎤 Transcribing...",
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        # Should return None (can't append without message_id)
        assert result is None

    async def test_append_handles_stale_message_id(self, session_manager, tmp_path):
        """Test that append handles stale message_id (edit fails)."""
        # Create session first
        session = await db.create_session(
            computer_name="TestComputer",
            tmux_session_name="test-stale-tmux",
            origin_adapter="telegram",
            adapter_metadata={"chat_id": "123", "topic_id": "456"},
        )
        session_id = session.session_id

        # Create output file
        output_file = tmp_path / f"{session_id[:8]}.txt"
        output_file.write_text("some output")

        # Create test adapter with edit failure
        adapter = TestUiAdapter(None)
        adapter._mock_edit_message = AsyncMock(return_value=False)  # Edit fails
        adapter._mock_send_message = AsyncMock(return_value=None)  # Fallback send also returns None

        # Set message ID
        await db.update_ux_state(session_id, output_message_id="msg-stale")

        # Try to append (should fail edit, then fallthrough to send new which also returns None)
        result = await adapter.send_status_message(
            session_id=session_id,
            text="🎤 Transcribing...",
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        # Should return None (both edit and send failed)
        assert result is None

        # Verify message_id was cleared
        ux_state = await db.get_ux_state(session_id)
        assert ux_state.output_message_id is None
