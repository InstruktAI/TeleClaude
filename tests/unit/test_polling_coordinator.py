"""Unit tests for polling_coordinator module."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.models import Session
from teleclaude.core.output_poller import IdleDetected, OutputChanged, ProcessExited


@pytest.mark.asyncio
class TestPollAndSendOutput:
    """Test poll_and_send_output function."""

    async def test_duplicate_polling_prevention(self):
        """Test polling request ignored when already polling."""
        session_manager = Mock()
        output_poller = Mock()
        get_adapter_for_session = AsyncMock()
        get_output_file = Mock()            # Already polling
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
        # Mock session with human-readable title (not AI-to-AI)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Session"  # Not matching $X > $Y pattern
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
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
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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
        # Mock session with human-readable title (not AI-to-AI)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Session"
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
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
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Session"
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
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
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Session"
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
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
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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

                    # Verify send_exit_message NOT called (exit code path)
                    mock_output_mgr.send_exit_message.assert_not_called()

    async def test_process_exited_without_exit_code(self, tmp_path):
        """Test ProcessExited event without exit code (session died)."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Session"
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
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
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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

                # Verify send_output_update NOT called (session died path)
                mock_output_mgr.send_output_update.assert_not_called()

    async def test_cleanup_in_finally_block(self):
        """Test cleanup always happens in finally block."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Session"
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
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
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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


class TestAISessionDetection:
    """Test AI-to-AI session detection via metadata."""

    def test_is_ai_to_ai_session_with_metadata_flag(self):
        """Test detection via is_ai_to_ai metadata flag."""
        from teleclaude.core.polling_coordinator import _is_ai_to_ai_session

        # AI-to-AI session (has metadata flag)
        ai_session = Session(
            session_id="test-ai",
            computer_name="comp1",
            tmux_session_name="comp1-ai-123",
            adapter_type="telegram",
            title="$comp1 > $comp2 - Test",
            adapter_metadata={"channel_id": "123", "is_ai_to_ai": True}
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
            adapter_type="telegram",
            title="Human Session",
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
            adapter_type="telegram",
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
            adapter_type="telegram",
            adapter_metadata={"channel_id": "123", "is_ai_to_ai": False}
        )
        assert not _is_ai_to_ai_session(session_false_flag)

        # Empty metadata dict
        session_empty_metadata = Session(
            session_id="test",
            computer_name="comp1",
            tmux_session_name="comp1-123",
            adapter_type="telegram",
            adapter_metadata={}
        )
        assert not _is_ai_to_ai_session(session_empty_metadata)


@pytest.mark.asyncio
class TestAIChunkedOutput:
    """Test AI-to-AI chunked output sending."""

    async def test_send_output_chunks_single_chunk(self):
        """Test AI mode with output under chunk size."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter = Mock()
        adapter.get_max_message_length = Mock(return_value=4096)
        adapter.send_message = AsyncMock()
        session_manager = Mock()

        short_output = "ls -la\ntotal 8\ndrwxr-xr-x  3 user  staff  96 Nov  4 10:00 ."

        await _send_output_chunks_ai_mode("test-123", adapter, short_output, session_manager)

        # Should send 2 messages: 1 chunk + completion marker
        assert adapter.send_message.call_count == 2

        # First call: chunk with sequence marker
        first_call = adapter.send_message.call_args_list[0]
        assert first_call[0][0] == "test-123"
        assert "```sh" in first_call[0][1]
        assert short_output in first_call[0][1]
        assert "[Chunk 1/1]" in first_call[0][1]

        # Second call: completion marker
        second_call = adapter.send_message.call_args_list[1]
        assert second_call[0][1] == "[Output Complete]"

    async def test_send_output_chunks_multiple_chunks(self):
        """Test AI mode with output requiring multiple chunks."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter = Mock()
        adapter.get_max_message_length = Mock(return_value=200)  # Small for testing
        adapter.send_message = AsyncMock()
        session_manager = Mock()

        # Output that will require multiple chunks (chunk_size = 200 - 100 = 100)
        long_output = "x" * 250  # Will create 3 chunks

        await _send_output_chunks_ai_mode("test-123", adapter, long_output, session_manager)

        # Should send 4 messages: 3 chunks + completion
        assert adapter.send_message.call_count == 4

        # Verify chunk markers
        chunks = adapter.send_message.call_args_list[:-1]  # All but completion
        for idx, call in enumerate(chunks, 1):
            assert f"[Chunk {idx}/3]" in call[0][1]

    async def test_send_output_chunks_preserves_order(self):
        """Test chunks sent with delay to preserve order."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode
        import asyncio

        adapter = Mock()
        adapter.get_max_message_length = Mock(return_value=200)
        adapter.send_message = AsyncMock()
        session_manager = Mock()

        with patch("teleclaude.core.polling_coordinator.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = AsyncMock()

            await _send_output_chunks_ai_mode("test-123", adapter, "x" * 250, session_manager)

            # Should sleep between chunks (3 chunks = 3 sleeps)
            assert mock_sleep.call_count == 3
            mock_sleep.assert_called_with(0.1)

    async def test_send_output_chunks_with_empty_output(self):
        """Test AI chunking with empty output."""
        from teleclaude.core.polling_coordinator import _send_output_chunks_ai_mode

        adapter = Mock()
        adapter.get_max_message_length = Mock(return_value=4096)
        adapter.send_message = AsyncMock()

        await _send_output_chunks_ai_mode("test-123", adapter, "", Mock())

        # Empty output produces no chunks, only completion marker (1 message)
        assert adapter.send_message.call_count == 1
        # Verify it's the completion marker
        adapter.send_message.assert_called_once_with("test-123", "[Output Complete]")


@pytest.mark.asyncio
class TestDualModePolling:
    """Test polling coordinator routes to AI vs Human mode correctly."""

    async def test_ai_session_uses_chunked_output(self):
        """Test AI-to-AI session uses chunking mode."""
        # Mock AI session (has is_ai_to_ai metadata flag)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="$mac1 > $mac2 - Deploy Script",
            adapter_metadata={"channel_id": "123", "is_ai_to_ai": True}
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.get_idle_notification_message_id = AsyncMock(return_value=None)
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        adapter.get_max_message_length = Mock(return_value=4096)
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller to yield OutputChanged
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(
                session_id="test-123", output="test ai output", started_at=1000.0, last_changed_at=1001.0
            )

        output_poller = Mock()
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
            mock_state.mark_polling = Mock()
            mock_state.get_exit_marker = Mock(return_value=False)
            mock_state.unmark_polling = Mock()
            mock_state.remove_exit_marker = Mock()

            with patch("teleclaude.core.polling_coordinator._send_output_chunks_ai_mode") as mock_ai_mode:
                mock_ai_mode.return_value = AsyncMock()

                # Execute
                await polling_coordinator.poll_and_send_output(
                    "test-123",
                    "test-tmux",
                    session_manager,
                    output_poller,
                    get_adapter_for_session,
                    get_output_file,
                )

                # Verify AI chunking used (NOT output_message_manager)
                mock_ai_mode.assert_called_once_with("test-123", adapter, "test ai output", session_manager)

    async def test_human_session_uses_edit_mode(self):
        """Test human session uses existing edit-in-place mode."""
        # Mock human session (does NOT match AI pattern)
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Human Terminal Session",  # NOT AI pattern
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=mock_session)
        session_manager.get_output_message_id = AsyncMock(return_value=None)
        session_manager.get_idle_notification_message_id = AsyncMock(return_value=None)
        session_manager.set_idle_notification_message_id = AsyncMock()

        adapter = Mock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        output_file = Path("/tmp/output.txt")
        get_output_file = Mock(return_value=output_file)

        # Mock poller
        async def mock_poll(session_id, tmux_session_name, output_file, has_exit_marker):
            yield OutputChanged(
                session_id="test-123", output="human output", started_at=1000.0, last_changed_at=1001.0
            )

        output_poller = Mock()
        output_poller.poll = mock_poll            mock_state.is_polling = Mock(return_value=False)
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

                # Verify edit mode used (NOT AI chunking)
                mock_output_mgr.send_output_update.assert_called_once_with(
                    "test-123", adapter, "human output", 1000.0, 1001.0, session_manager, max_message_length=3800
                )
