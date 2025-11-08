"""Unit tests for UiAdapter base class."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import db, Db


class TestableUiAdapter(UiAdapter):
    """Concrete implementation of UiAdapter for testing."""

    def __init__(self):
        super().__init__()
        self.adapter_client = None  # Set directly
        self._send_message_mock = AsyncMock(return_value="msg-123")
        self._edit_message_mock = AsyncMock(return_value=True)
        self._delete_message_mock = AsyncMock(return_value=True)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(self, session_id: str, text: str, metadata=None) -> str:
        return await self._send_message_mock(session_id, text, metadata)

    async def edit_message(self, session_id: str, message_id: str, text: str) -> bool:
        return await self._edit_message_mock(session_id, message_id, text)

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        return await self._delete_message_mock(session_id, message_id)

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

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0):
        """Mock implementation."""
        yield "test output"

    async def set_channel_status(self, session_id: str, status: str) -> bool:
        """Mock implementation."""
        return True


@pytest.fixture
async def test_db(tmp_path):
    """Create temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    test_db_instance = Db(db_path)
    await test_db_instance.initialize()

    # Patch module-level db with test instance
    with patch("teleclaude.adapters.ui_adapter.db", test_db_instance):
        yield test_db_instance

    await test_db_instance.close()


@pytest.mark.asyncio
class TestSendOutputUpdate:
    """Test send_output_update method."""

    async def test_creates_new_message_when_no_message_id(self, test_db):
        """Test creating new output message when no message_id exists."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )

        result = await adapter.send_output_update(
            session.session_id,
            "test output",
            time.time(),
            time.time(),
        )

        assert result == "msg-123"
        adapter._send_message_mock.assert_called_once()
        adapter._edit_message_mock.assert_not_called()

    async def test_edits_existing_message_when_message_id_exists(self, test_db):
        """Test editing existing message when message_id exists."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )
        await test_db.update_ux_state(session.session_id, output_message_id="msg-456")

        result = await adapter.send_output_update(
            session.session_id,
            "updated output",
            time.time(),
            time.time(),
        )

        assert result == "msg-456"
        adapter._edit_message_mock.assert_called_once()
        adapter._send_message_mock.assert_not_called()

    async def test_creates_new_when_edit_fails(self, test_db):
        """Test creating new message when edit fails (stale message_id)."""
        adapter = TestableUiAdapter()
        adapter._edit_message_mock = AsyncMock(return_value=False)
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )
        await test_db.update_ux_state(session.session_id, output_message_id="msg-stale")

        result = await adapter.send_output_update(
            session.session_id,
            "output after edit fail",
            time.time(),
            time.time(),
        )

        assert result == "msg-123"
        adapter._edit_message_mock.assert_called_once()
        adapter._send_message_mock.assert_called_once()

        # Verify stale message_id was cleared
        ux_state = await test_db.get_ux_state(session.session_id)
        assert ux_state.output_message_id == "msg-123"

    async def test_includes_exit_code_in_final_message(self, test_db):
        """Test final message includes exit code."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )

        started_at = time.time() - 10  # 10 seconds ago
        await adapter.send_output_update(
            session.session_id,
            "command output",
            started_at,
            time.time(),
            is_final=True,
            exit_code=0,
        )

        adapter._send_message_mock.assert_called_once()
        call_args = adapter._send_message_mock.call_args
        message_text = call_args[0][1]

        assert "✅" in message_text or "0" in message_text
        assert "```" in message_text


@pytest.mark.asyncio
class TestSendStatusMessage:
    """Test send_status_message method."""

    async def test_sends_new_message_when_append_false(self, test_db):
        """Test sending new status message."""
        adapter = TestableUiAdapter()

        result = await adapter.send_status_message(
            "test-session",
            "Status message",
            append_to_existing=False,
        )

        assert result == "msg-123"
        adapter._send_message_mock.assert_called_once_with("test-session", "Status message", None)

    async def test_appends_to_existing_output_message(self, test_db, tmp_path):
        """Test appending status to existing output message."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )
        await test_db.update_ux_state(session.session_id, output_message_id="msg-existing")

        output_file = tmp_path / "output.txt"
        output_file.write_text("existing output")

        result = await adapter.send_status_message(
            session.session_id,
            "🎤 Transcribing...",
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        assert result == "msg-existing"
        adapter._edit_message_mock.assert_called_once()
        call_args = adapter._edit_message_mock.call_args
        edited_text = call_args[0][2]

        assert "existing output" in edited_text
        assert "🎤 Transcribing..." in edited_text

    async def test_append_returns_none_when_no_message_id(self, test_db, tmp_path):
        """Test append returns None when no message_id exists."""
        adapter = TestableUiAdapter()
        output_file = tmp_path / "output.txt"
        output_file.write_text("some output")

        result = await adapter.send_status_message(
            "test-session",
            "Status",
            append_to_existing=True,
            output_file_path=str(output_file),
        )

        assert result is None
        adapter._edit_message_mock.assert_not_called()


@pytest.mark.asyncio
class TestSendExitMessage:
    """Test send_exit_message method."""

    async def test_sends_exit_message(self, test_db):
        """Test sending exit message."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )

        await adapter.send_exit_message(
            session.session_id,
            "final output",
            "✅ Process exited",
        )

        adapter._send_message_mock.assert_called_once()
        call_args = adapter._send_message_mock.call_args
        message_text = call_args[0][1]

        assert "final output" in message_text
        assert "✅ Process exited" in message_text

    async def test_edits_existing_message_on_exit(self, test_db):
        """Test editing existing message on exit."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )
        await test_db.update_ux_state(session.session_id, output_message_id="msg-existing")

        await adapter.send_exit_message(
            session.session_id,
            "final output",
            "✅ Process exited",
        )

        adapter._edit_message_mock.assert_called_once()
        adapter._send_message_mock.assert_not_called()


@pytest.mark.asyncio
class TestCleanupFeedbackMessages:
    """Test cleanup_feedback_messages method."""

    async def test_deletes_pending_messages(self, test_db):
        """Test deleting pending feedback messages."""
        adapter = TestableUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )
        await test_db.update_ux_state(
            session.session_id,
            pending_deletions=["msg-1", "msg-2", "msg-3"],
        )

        await adapter.cleanup_feedback_messages(session.session_id)

        assert adapter._delete_message_mock.call_count == 3
        ux_state = await test_db.get_ux_state(session.session_id)
        assert ux_state.pending_deletions == []

    async def test_handles_delete_failures_gracefully(self, test_db):
        """Test handling delete failures without raising."""
        adapter = TestableUiAdapter()
        adapter._delete_message_mock = AsyncMock(side_effect=Exception("Delete failed"))
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
        )
        await test_db.update_ux_state(
            session.session_id,
            pending_deletions=["msg-1"],
        )

        # Should not raise
        await adapter.cleanup_feedback_messages(session.session_id)

        ux_state = await test_db.get_ux_state(session.session_id)
        assert ux_state.pending_deletions == []
