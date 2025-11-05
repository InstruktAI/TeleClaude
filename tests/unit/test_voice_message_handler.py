"""Unit tests for voice_message_handler module."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import voice_message_handler
from teleclaude.core.models import Session


@pytest.mark.asyncio
class TestHandleVoice:
    """Test handle_voice function."""

    async def test_session_not_found(self, tmp_path):
        """Test voice handler when session doesn't exist."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=None)

        get_adapter_for_session = AsyncMock()
        get_output_file = Mock()

        context = {"duration": 5}

        # Execute
        await voice_message_handler.handle_voice(
            session_id="nonexistent",
            audio_path=str(audio_file),
            context=context,
            session_manager=session_manager,
            get_adapter_for_session=get_adapter_for_session,
            get_output_file=get_output_file,
        )

        # Verify no further processing
        get_adapter_for_session.assert_not_called()

    async def test_no_active_process_rejects_voice(self, tmp_path):
        """Test voice rejected when no active process running."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
            session_id="test-123",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)

        adapter = Mock()
        adapter.send_message = AsyncMock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock()
        context = {"duration": 5}

        session_manager.is_polling = AsyncMock(return_value=False)

            # Execute
        await voice_message_handler.handle_voice(
            session_id="test-123",
            audio_path=str(audio_file),
            context=context,
            session_manager=session_manager,
            get_adapter_for_session=get_adapter_for_session,
            get_output_file=get_output_file,
        )

            # Verify rejection message sent
        adapter.send_message.assert_called_once_with(
            "test-123", "🎤 Voice input requires an active process (e.g., claude, vim)"
        )

            # Verify audio file cleaned up
        assert not audio_file.exists()

    async def test_no_active_process_cleanup_error(self, tmp_path):
        """Test cleanup error handling when no active process."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-cleanup-1",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)

        adapter = Mock()
        adapter.send_message = AsyncMock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock()
        context = {"duration": 5}

        session_manager.is_polling = AsyncMock(return_value=False)

        # Mock Path.unlink to raise exception
        with patch("teleclaude.core.voice_message_handler.Path") as mock_path_class:
            mock_path = Mock()
            mock_path.unlink = Mock(side_effect=PermissionError("Cannot delete"))
            mock_path_class.return_value = mock_path

                # Execute - should not raise exception
            await voice_message_handler.handle_voice(
                session_id="test-cleanup-1",
                audio_path=str(audio_file),
                context=context,
                session_manager=session_manager,
                get_adapter_for_session=get_adapter_for_session,
                get_output_file=get_output_file,
            )

                # Verify rejection message still sent
            adapter.send_message.assert_called_once()

    async def test_no_output_message_yet_rejects_voice(self, tmp_path):
        """Test voice rejected when polling started but no output message yet."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-456",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value=None)  # No message yet

        adapter = Mock()
        adapter.send_message = AsyncMock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))
        context = {"duration": 3}

        session_manager.is_polling = AsyncMock(return_value=True)

            # Execute
        await voice_message_handler.handle_voice(
            session_id="test-456",
            audio_path=str(audio_file),
            context=context,
            session_manager=session_manager,
            get_adapter_for_session=get_adapter_for_session,
            get_output_file=get_output_file,
        )

            # Verify rejection message sent
        adapter.send_message.assert_called_once_with(
            "test-456",
            "⚠️ Voice input unavailable - output message not ready yet (try again in 1-2 seconds)",
        )

            # Verify audio file cleaned up
        assert not audio_file.exists()

    async def test_no_output_message_cleanup_error(self, tmp_path):
        """Test cleanup error handling when no output message yet."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-cleanup-2",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value=None)

        adapter = Mock()
        adapter.send_message = AsyncMock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))
        context = {"duration": 3}

        session_manager.is_polling = AsyncMock(return_value=False)

        # Mock Path.unlink to raise exception
        with patch("teleclaude.core.voice_message_handler.Path") as mock_path_class:
            mock_path = Mock()
            mock_path.unlink = Mock(side_effect=OSError("Cannot delete"))
            mock_path_class.return_value = mock_path

                # Execute - should not raise exception
            await voice_message_handler.handle_voice(
                session_id="test-cleanup-2",
                audio_path=str(audio_file),
                context=context,
                session_manager=session_manager,
                get_adapter_for_session=get_adapter_for_session,
                get_output_file=get_output_file,
            )

                # Verify rejection message still sent
            adapter.send_message.assert_called_once()

    async def test_topic_deleted_during_transcription(self, tmp_path):
        """Test voice handler when topic is deleted (send_status_message returns None)."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-789",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value="msg-123")

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))
        context = {"duration": 2}

        session_manager.is_polling = AsyncMock(return_value=False)

        with patch("teleclaude.core.voice_message_handler.output_message_manager") as mock_output_mgr:
                # send_status_message returns None (topic deleted)
            mock_output_mgr.send_status_message = AsyncMock(return_value=None)

                # Execute
            await voice_message_handler.handle_voice(
                session_id="test-789",
                audio_path=str(audio_file),
                context=context,
                session_manager=session_manager,
                get_adapter_for_session=get_adapter_for_session,
                get_output_file=get_output_file,
            )

                # Verify audio file cleaned up
            assert not audio_file.exists()

    async def test_topic_deleted_cleanup_error(self, tmp_path):
        """Test cleanup error handling when topic is deleted."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-cleanup-3",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value="msg-123")

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))
        context = {"duration": 2}

        session_manager.is_polling = AsyncMock(return_value=False)

        with patch("teleclaude.core.voice_message_handler.output_message_manager") as mock_output_mgr:
                # send_status_message returns None (topic deleted)
            mock_output_mgr.send_status_message = AsyncMock(return_value=None)

                # Mock Path.unlink to raise exception
            with patch("teleclaude.core.voice_message_handler.Path") as mock_path_class:
                mock_path = Mock()
                mock_path.unlink = Mock(side_effect=IOError("Cannot delete"))
                mock_path_class.return_value = mock_path

                    # Execute - should not raise exception
                await voice_message_handler.handle_voice(
                    session_id="test-cleanup-3",
                    audio_path=str(audio_file),
                    context=context,
                    session_manager=session_manager,
                    get_adapter_for_session=get_adapter_for_session,
                    get_output_file=get_output_file,
                )

                    # Verify cleanup was attempted
                mock_path.unlink.assert_called()

    async def test_transcription_failure(self, tmp_path):
        """Test voice handler when transcription fails."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-999",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={"output_message_id": "msg-456"})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value="msg-456")

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=tmp_path / "output.txt")
        context = {"duration": 4}

        session_manager.is_polling = AsyncMock(return_value=True)

        with patch("teleclaude.core.voice_message_handler.output_message_manager") as mock_output_mgr:
            mock_output_mgr.send_status_message = AsyncMock(side_effect=["msg-123", None])

            with patch("teleclaude.core.voice_message_handler.transcribe_voice_with_retry") as mock_transcribe:
                    # Transcription fails (returns None)
                mock_transcribe.return_value = None

                    # Execute
                await voice_message_handler.handle_voice(
                    session_id="test-999",
                    audio_path=str(audio_file),
                    context=context,
                    session_manager=session_manager,
                    get_adapter_for_session=get_adapter_for_session,
                    get_output_file=get_output_file,
                )

                    # Verify error message sent
                assert mock_output_mgr.send_status_message.call_count == 2
                second_call = mock_output_mgr.send_status_message.call_args_list[1]
                assert "❌ Transcription failed" in second_call[0][2]

                    # Verify audio file cleaned up
                assert not audio_file.exists()

    async def test_terminal_send_failure(self, tmp_path):
        """Test voice handler when sending to terminal fails."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-111",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value="msg-789")
        session_manager.update_last_activity = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=tmp_path / "output.txt")
        context = {"duration": 6}

        session_manager.is_polling = AsyncMock(return_value=True)  # Process is running
        session_manager.get_ux_state = AsyncMock(return_value={"output_message_id": "msg-789"})  # Has output message

        with patch("teleclaude.core.voice_message_handler.output_message_manager") as mock_output_mgr:
            mock_output_mgr.send_status_message = AsyncMock(return_value="msg-123")

            with patch("teleclaude.core.voice_message_handler.transcribe_voice_with_retry") as mock_transcribe:
                mock_transcribe.return_value = "test input text"

                with patch("teleclaude.core.voice_message_handler.terminal_bridge") as mock_terminal:
                        # send_keys fails
                    mock_terminal.send_keys = AsyncMock(return_value=False)

                        # Execute
                    await voice_message_handler.handle_voice(
                        session_id="test-111",
                        audio_path=str(audio_file),
                        context=context,
                        session_manager=session_manager,
                        get_adapter_for_session=get_adapter_for_session,
                        get_output_file=get_output_file,
                    )

                        # Verify error message sent
                    adapter.send_message.assert_called_once_with(
                        "test-111", "❌ Failed to send input to terminal"
                    )

                        # Verify audio file cleaned up
                    assert not audio_file.exists()

    async def test_successful_voice_input(self, tmp_path):
        """Test successful voice transcription and input to terminal."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-222",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={"output_message_id": "msg-999"})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value="msg-999")
        session_manager.update_last_activity = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=tmp_path / "output.txt")
        context = {"duration": 3}

        session_manager.is_polling = AsyncMock(return_value=True)

        with patch("teleclaude.core.voice_message_handler.output_message_manager") as mock_output_mgr:
            mock_output_mgr.send_status_message = AsyncMock(return_value="msg-status")

            with patch("teleclaude.core.voice_message_handler.transcribe_voice_with_retry") as mock_transcribe:
                mock_transcribe.return_value = "hello world"

                with patch("teleclaude.core.voice_message_handler.terminal_bridge") as mock_terminal:
                    mock_terminal.send_keys = AsyncMock(return_value=True)

                        # Execute
                    await voice_message_handler.handle_voice(
                        session_id="test-222",
                        audio_path=str(audio_file),
                        context=context,
                        session_manager=session_manager,
                        get_adapter_for_session=get_adapter_for_session,
                        get_output_file=get_output_file,
                    )

                        # Verify transcribing status sent
                    mock_output_mgr.send_status_message.assert_called_once()

                        # Verify transcription called
                    mock_transcribe.assert_called_once_with(str(audio_file))

                        # Verify text sent to terminal
                    mock_terminal.send_keys.assert_called_once_with(
                        "test-tmux",
                        "hello world",
                        append_exit_marker=False,
                    )

                        # Verify activity updated
                    session_manager.update_last_activity.assert_called_once_with("test-222")

                        # Verify audio file cleaned up
                    assert not audio_file.exists()

    async def test_file_cleanup_error_handling(self, tmp_path):
        """Test that file cleanup errors are handled gracefully."""
        audio_file = tmp_path / "test_audio.ogg"
        audio_file.write_text("fake audio")

        session = Session(
        session_id="test-cleanup",
        computer_name="TestMac",
        tmux_session_name="test-tmux",
        adapter_type="telegram",
        title="Test",
        )

        session_manager = Mock()
        session_manager.get_ux_state = AsyncMock(return_value={"output_message_id": "msg-123"})
        session_manager.update_ux_state = AsyncMock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.get_output_message_id = AsyncMock(return_value="msg-123")
        session_manager.update_last_activity = AsyncMock()

        adapter = Mock()
        adapter.send_message = AsyncMock()
        get_adapter_for_session = AsyncMock(return_value=adapter)

        get_output_file = Mock(return_value=tmp_path / "output.txt")
        context = {"duration": 3}

        session_manager.is_polling = AsyncMock(return_value=True)

        with patch("teleclaude.core.voice_message_handler.output_message_manager") as mock_output_mgr:
            mock_output_mgr.send_status_message = AsyncMock(return_value="msg-status")

            with patch("teleclaude.core.voice_message_handler.transcribe_voice_with_retry") as mock_transcribe:
                mock_transcribe.return_value = "transcribed text"

                with patch("teleclaude.core.voice_message_handler.terminal_bridge") as mock_terminal:
                    mock_terminal.send_keys = AsyncMock(return_value=True)

                        # Mock Path.unlink to raise exception
                    with patch("teleclaude.core.voice_message_handler.Path") as mock_path_class:
                        mock_path = Mock()
                        mock_path.unlink = Mock(side_effect=PermissionError("Cannot delete file"))
                        mock_path_class.return_value = mock_path

                            # Execute - should not raise exception despite file cleanup failure
                        await voice_message_handler.handle_voice(
                            session_id="test-cleanup",
                            audio_path=str(audio_file),
                            context=context,
                            session_manager=session_manager,
                            get_adapter_for_session=get_adapter_for_session,
                            get_output_file=get_output_file,
                        )

                            # Verify unlink was attempted
                        mock_path.unlink.assert_called()

                            # Verify transcription still succeeded despite cleanup error
                        mock_transcribe.assert_called_once()
                        mock_terminal.send_keys.assert_called_once()
