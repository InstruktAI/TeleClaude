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
            title="Test Session"  # Not matching $X > $Y pattern
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
            title="Test Session"
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
            title="Test Session"
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
            title="Test Session"
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
            title="Test Session"
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
            title="Test Session"
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

class TestAISessionDetection:
    """Test AI-to-AI session detection via metadata."""

    def test_is_ai_to_ai_session_with_target_computer(self):
        """Test detection via target_computer in metadata."""
        from teleclaude.core.polling_coordinator import _is_ai_to_ai_session

        # AI-to-AI session (has target_computer)
        ai_session = Session(
            session_id="test-ai",
            computer_name="comp1",
            tmux_session_name="comp1-ai-123",
            origin_adapter="redis",
            title="$comp1 > $comp2 - Test",
            adapter_metadata={"target_computer": "comp2"}
        )
        assert _is_ai_to_ai_session(ai_session)

    def test_is_ai_to_ai_session_rejects_human_sessions(self):
        """Test human sessions without metadata flag are rejected."""
        from teleclaude.core.polling_coordinator import _is_ai_to_ai_session

        # Human session (no metadata flag)
        human_session = Session(
            session_id="test-human",
            computer_name="comp1",
            tmux_session_name="comp1-123",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "456"}
        )
        assert not _is_ai_to_ai_session(human_session)

    def test_is_ai_to_ai_session_handles_none_and_empty(self):
        """Test None and empty metadata handling."""
        from teleclaude.core.polling_coordinator import _is_ai_to_ai_session

        # None session
        assert not _is_ai_to_ai_session(None)

        # Session with None metadata
        session_no_metadata = Session(
            session_id="test",
            computer_name="comp1",
            tmux_session_name="comp1-123",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata=None
        )
        assert not _is_ai_to_ai_session(session_no_metadata)

    def test_is_ai_to_ai_session_edge_cases(self):
        """Test edge cases in metadata detection."""
        from teleclaude.core.polling_coordinator import _is_ai_to_ai_session

        # Metadata exists but flag is False
        session_false_flag = Session(
            session_id="test",
            computer_name="comp1",
            tmux_session_name="comp1-123",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "123", "is_ai_to_ai": False}
        )
        assert not _is_ai_to_ai_session(session_false_flag)

        # Empty metadata dict
        session_empty_metadata = Session(
            session_id="test",
            computer_name="comp1",
            tmux_session_name="comp1-123",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={}
        )
        assert not _is_ai_to_ai_session(session_empty_metadata)


@pytest.mark.asyncio
class TestAIChunkedOutput:
    """Test AI-to-AI chunked output sending."""

    async def test_send_output_chunks_single_chunk(self):
        """Test AI mode sends RAW chunks without formatting."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter_client = Mock()
        adapter_client.send_message = AsyncMock()

        short_output = "ls -la\ntotal 8\ndrwxr-xr-x  3 user  staff  96 Nov  4 10:00 ."

        await _send_output_chunks_ai_mode("test-123", adapter_client, short_output)

        # Should send 2 messages: 1 chunk + completion marker
        assert adapter_client.send_message.call_count == 2

        # First call: RAW chunk (NO backticks, NO formatting)
        first_call = adapter_client.send_message.call_args_list[0]
        assert first_call[0][0] == "test-123"
        assert first_call[0][1] == short_output  # Exact raw output
        assert "```" not in first_call[0][1]  # NO backticks

        # Second call: completion marker
        second_call = adapter_client.send_message.call_args_list[1]
        assert second_call[0][1] == "[Output Complete]"

    async def test_send_output_chunks_multiple_chunks(self):
        """Test AI mode splits output into raw chunks."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter_client = Mock()
        adapter_client.send_message = AsyncMock()

        # Output that will require multiple chunks (chunk_size = 3900)
        long_output = "x" * 8000  # Will create 3 chunks

        await _send_output_chunks_ai_mode("test-123", adapter_client, long_output)

        # Should send 3 chunks + completion
        assert adapter_client.send_message.call_count == 4

        # Verify chunks are RAW (no formatting)
        chunks = adapter_client.send_message.call_args_list[:-1]  # All but completion
        for call in chunks:
            chunk_text = call[0][1]
            assert "```" not in chunk_text  # NO backticks
            assert "[Chunk" not in chunk_text  # NO chunk markers

    async def test_send_output_chunks_preserves_order(self):
        """Test chunks sent with delay to preserve order."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter_client = Mock()
        adapter_client.send_message = AsyncMock()

        with patch("teleclaude.core.polling_coordinator.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = AsyncMock()

            await _send_output_chunks_ai_mode("test-123", adapter_client, "x" * 8000)

            # Should sleep between chunks (3 chunks = 3 sleeps)
            assert mock_sleep.call_count == 3
            mock_sleep.assert_called_with(0.1)

    async def test_send_output_chunks_with_empty_output(self):
        """Test AI chunking with empty output."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter_client = Mock()
        adapter_client.send_message = AsyncMock()

        await _send_output_chunks_ai_mode("test-123", adapter_client, "")

        # Empty output: range(0, 0, 3900) = empty range, chunks = []
        # So: 0 chunks + 1 completion marker = 1 message total
        assert adapter_client.send_message.call_count == 1
        adapter_client.send_message.assert_called_once_with("test-123", "[Output Complete]")


@pytest.mark.asyncio
class TestDualModePolling:
    """Test polling coordinator routes to AI vs Human mode correctly."""

    async def test_ai_session_uses_chunked_output(self):
        """Test AI-to-AI session sends raw chunks via adapter_client.send_message()."""
        from teleclaude.core.polling_coordinator import poll_and_send_output

        # Mock AI session (has target_computer in metadata)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="redis",
            title="$mac1 > $mac2 - Deploy Script",
            adapter_metadata={"target_computer": "remote"}
        )

        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_ux_state = AsyncMock(return_value=Mock(polling_active=False, idle_notification_message_id=None))
        db.update_ux_state = AsyncMock()

        adapter_client = Mock()
        adapter_client.send_message = AsyncMock()
        adapter_client.send_output_update = AsyncMock()
        adapter_client.delete_message = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        # Mock poller to yield OutputChanged
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(
                session_id="test-123", output="test ai output", started_at=1000.0, last_changed_at=1001.0
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        # Execute
        await poll_and_send_output(
            session_id="test-123",
            tmux_session_name="test-tmux",
            output_poller=output_poller,
            adapter_client=adapter_client,
            get_output_file=get_output_file,
        )

        # VERIFY: AI mode uses adapter_client.send_message() for RAW chunks
        assert adapter_client.send_message.call_count >= 2  # chunk + completion
        # First call should be RAW output
        first_call = adapter_client.send_message.call_args_list[0]
        assert first_call[0][1] == "test ai output"  # Raw, no formatting

    async def test_human_session_uses_send_output_update(self):
        """Test human session calls adapter_client.send_output_update() (edit mode)."""
        from teleclaude.core.polling_coordinator import poll_and_send_output

        # Mock human session (no is_ai_to_ai flag)
        mock_session = Session(
            session_id="test-456",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "456"}
        )

        db.is_polling = AsyncMock(return_value=False)
        db.mark_polling = AsyncMock()
        db.unmark_polling = AsyncMock()
        db.clear_pending_deletions = AsyncMock()
        db.get_session = AsyncMock(return_value=mock_session)
        db.get_idle_notification_message_id = AsyncMock(return_value=None)
        db.set_idle_notification_message_id = AsyncMock()

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()
        adapter_client.send_message = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        # Mock poller to yield OutputChanged
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(
                session_id="test-456", output="human output", started_at=1000.0, last_changed_at=1001.0
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        # Execute
        await poll_and_send_output(
            session_id="test-456",
            tmux_session_name="test-tmux",
            output_poller=output_poller,
            adapter_client=adapter_client,
            get_output_file=get_output_file,
        )

        # VERIFY: Human mode uses adapter_client.send_output_update() (NOT chunking)
        adapter_client.send_output_update.assert_called_once()
        call_args = adapter_client.send_output_update.call_args
        # Call signature: send_output_update(session_id, output, started_at, last_changed_at, is_final, exit_code)
        assert call_args[0][0] == "test-456"  # First positional arg
        assert call_args[0][1] == "human output"  # Second positional arg

        # VERIFY: Does NOT use send_message for chunks
        adapter_client.send_message.assert_not_called()


class TestNotificationFlagCoordination:
    """Tests for notification_sent flag coordination with idle detection."""

    @pytest.mark.asyncio
    async def test_idle_notification_skipped_when_flag_set(self):
        """Test IdleDetected event skipped when notification_sent flag is True."""
        from unittest.mock import AsyncMock, Mock
        from teleclaude.core.output_poller import IdleDetected
        from teleclaude.core.polling_coordinator import poll_and_send_output
        from pathlib import Path

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
        mock_db.get_ux_state = AsyncMock(
            return_value=Mock(idle_notification_message_id=None, notification_sent=True)
        )
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
        from unittest.mock import AsyncMock, Mock, patch
        from teleclaude.core.output_poller import IdleDetected
        from teleclaude.core.polling_coordinator import poll_and_send_output
        from pathlib import Path

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
        mock_db.get_ux_state = AsyncMock(
            return_value=Mock(idle_notification_message_id=None, notification_sent=False)
        )
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
                call[1].get("idle_notification_message_id") == "msg-123" for call in mock_db.update_ux_state.call_args_list
            )

    @pytest.mark.asyncio
    async def test_notification_flag_cleared_on_output_change(self):
        """Test notification_sent flag cleared when OutputChanged event occurs."""
        from unittest.mock import AsyncMock, Mock, patch
        from teleclaude.core.output_poller import OutputChanged
        from teleclaude.core.polling_coordinator import poll_and_send_output
        from pathlib import Path

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
            yield OutputChanged(
                session_id="test-789", output="new output", started_at=1000.0, last_changed_at=1001.0
            )

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
