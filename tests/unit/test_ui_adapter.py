"""Unit tests for UiAdapter base class."""

import time
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import Db
from teleclaude.core.models import (
    MessageMetadata,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)


class MockUiAdapter(UiAdapter):
    """Concrete implementation of UiAdapter for testing."""

    ADAPTER_KEY = "telegram"  # Use telegram key for testing (reuses existing metadata structure)

    def __init__(self):
        # Create mock client
        mock_client = AsyncMock()
        mock_client.on = AsyncMock()  # Mock event registration
        super().__init__(mock_client)
        self._send_message_mock = AsyncMock(return_value="msg-123")
        self._edit_message_mock = AsyncMock(return_value=True)
        self._delete_message_mock = AsyncMock(return_value=True)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(self, session: "Session", text: str, metadata=None) -> str:  # type: ignore[name-defined]
        return await self._send_message_mock(session, text, metadata)

    async def edit_message(self, session: "Session", message_id: str, text: str, metadata: MessageMetadata) -> bool:  # type: ignore[name-defined]
        return await self._edit_message_mock(session, message_id, text, metadata)

    async def delete_message(self, session: "Session", message_id: str) -> bool:  # type: ignore[name-defined]
        return await self._delete_message_mock(session, message_id)

    async def close_channel(self, session_id: str) -> bool:
        return True

    async def reopen_channel(self, session_id: str) -> bool:
        return True

    async def send_file(self, session_id: str, file_path: str, caption: str = "") -> str:
        return "file-msg-123"

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0):
        if False:
            yield
        return

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
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )

        result = await adapter.send_output_update(
            session,
            "test output",
            time.time(),
            time.time(),
        )

        assert result == "msg-123"
        adapter._send_message_mock.assert_called_once()
        adapter._edit_message_mock.assert_not_called()

    async def test_edits_existing_message_when_message_id_exists(self, test_db):
        """Test editing existing message when message_id exists."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )

        # Set output_message_id in adapter namespace
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(output_message_id="msg-456")
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        # Refresh session from DB
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_output_update(
            session,
            "updated output",
            time.time(),
            time.time(),
        )

        assert result == "msg-456"
        adapter._edit_message_mock.assert_called_once()
        adapter._send_message_mock.assert_not_called()

    async def test_creates_new_when_edit_fails(self, test_db):
        """Test creating new message when edit fails (stale message_id)."""
        adapter = MockUiAdapter()
        adapter._edit_message_mock = AsyncMock(return_value=False)
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )

        # Set output_message_id in adapter namespace
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(output_message_id="msg-stale")
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        # Refresh session from DB
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_output_update(
            session,
            "output after edit fail",
            time.time(),
            time.time(),
        )

        assert result == "msg-123"
        adapter._edit_message_mock.assert_called_once()
        adapter._send_message_mock.assert_called_once()

        # Verify stale message_id was cleared and new one stored
        session = await test_db.get_session(session.session_id)
        assert session.adapter_metadata.telegram is not None
        assert session.adapter_metadata.telegram.output_message_id == "msg-123"

    async def test_includes_exit_code_in_final_message(self, test_db):
        """Test final message includes exit code."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )

        started_at = time.time() - 10  # 10 seconds ago
        await adapter.send_output_update(
            session,
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
class TestSendExitMessage:
    """Test send_exit_message method."""

    async def test_sends_exit_message(self, test_db):
        """Test sending exit message."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )

        await adapter.send_exit_message(
            session,
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
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )

        # Set output_message_id in adapter namespace
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(output_message_id="msg-existing")
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        # Refresh session from DB
        session = await test_db.get_session(session.session_id)

        await adapter.send_exit_message(
            session,
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
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )
        await test_db.update_ux_state(
            session.session_id,
            pending_feedback_deletions=["msg-1", "msg-2", "msg-3"],
        )

        await adapter.cleanup_feedback_messages(session)

        assert adapter._delete_message_mock.call_count == 3
        ux_state = await test_db.get_ux_state(session.session_id)
        assert ux_state.pending_feedback_deletions == []

    async def test_handles_delete_failures_gracefully(self, test_db):
        """Test handling delete failures without raising."""
        adapter = MockUiAdapter()
        adapter._delete_message_mock = AsyncMock(side_effect=Exception("Delete failed"))
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            origin_adapter="telegram",
            title="Test Session",
        )
        await test_db.update_ux_state(
            session.session_id,
            pending_feedback_deletions=["msg-1"],
        )

        # Should not raise
        await adapter.cleanup_feedback_messages(session)

        ux_state = await test_db.get_ux_state(session.session_id)
        assert ux_state.pending_feedback_deletions == []


class TestFormatMessage:
    """Test format_message method and markdown sanitization."""

    def test_sanitizes_internal_code_blocks(self):
        """Test that internal ``` markers are escaped to prevent nested code blocks."""
        adapter = MockUiAdapter()
        output_with_code = "Here is code:\n```python\nprint('hello')\n```\nEnd"

        result = adapter.format_message(output_with_code, "status line")

        # Should have outer code block markers
        assert result.startswith("```\n")
        # Internal ``` should be escaped with zero-width space
        assert "`\u200b``python" in result
        assert "`\u200b``\n" in result  # Closing marker also escaped

    def test_handles_multiple_code_blocks(self):
        """Test multiple internal code blocks are all escaped."""
        adapter = MockUiAdapter()
        output = "```js\ncode1\n```\ntext\n```py\ncode2\n```"

        result = adapter.format_message(output, "status")

        # Count escaped markers (should be 4 - two opening, two closing)
        assert result.count("`\u200b``") == 4
        # Should only have 2 real ``` markers (outer wrapper)
        assert result.count("```") == 2

    def test_preserves_output_without_code_blocks(self):
        """Test normal output without ``` is unchanged."""
        adapter = MockUiAdapter()
        output = "Simple terminal output\nNo code blocks here"

        result = adapter.format_message(output, "status line")

        assert "```\nSimple terminal output\nNo code blocks here\n```" in result
        assert "status line" in result
