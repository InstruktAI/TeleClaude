"""Unit tests for voice message handler."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_voice_handler():
    """Reset voice handler module state before each test."""
    from teleclaude.core import voice_message_handler

    voice_message_handler._openai_client = None
    yield
    voice_message_handler._openai_client = None


def test_init_voice_handler_initializes_client():
    """Test that init_voice_handler creates OpenAI client."""
    from teleclaude.core import voice_message_handler

    with patch("teleclaude.core.voice_message_handler.AsyncOpenAI") as mock_openai:
        voice_message_handler.init_voice_handler(api_key="test-api-key")

        mock_openai.assert_called_once_with(api_key="test-api-key")
        assert voice_message_handler._openai_client is not None


def test_init_voice_handler_is_idempotent():
    """Test that init_voice_handler is safe to call multiple times (idempotent)."""
    from teleclaude.core import voice_message_handler

    with patch("teleclaude.core.voice_message_handler.AsyncOpenAI") as mock_openai:
        # First call initializes
        voice_message_handler.init_voice_handler(api_key="test-api-key")
        assert mock_openai.call_count == 1

        # Second call is a no-op (idempotent)
        voice_message_handler.init_voice_handler(api_key="another-key")
        assert mock_openai.call_count == 1  # Still only called once


def test_init_voice_handler_requires_api_key():
    """Test that init_voice_handler requires API key."""
    from teleclaude.core import voice_message_handler

    # Clear environment variable
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            voice_message_handler.init_voice_handler()


@pytest.mark.asyncio
async def test_transcribe_voice_calls_whisper_api():
    """Test that transcribe_voice calls Whisper API."""
    from teleclaude.core.voice_message_handler import transcribe_voice

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        # Create mock client
        mock_client = MagicMock()
        mock_transcript = MagicMock()
        mock_transcript.text = "Hello world"
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcript)

        result = await transcribe_voice(audio_path, client=mock_client)

        assert result == "Hello world"
        mock_client.audio.transcriptions.create.assert_called_once()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_handles_file_not_found():
    """Test that transcribe_voice raises FileNotFoundError."""
    from teleclaude.core.voice_message_handler import transcribe_voice

    mock_client = MagicMock()

    with pytest.raises(FileNotFoundError):
        await transcribe_voice("/nonexistent/audio.ogg", client=mock_client)


@pytest.mark.asyncio
async def test_transcribe_voice_with_retry_retries_once():
    """Test that transcribe_voice_with_retry retries once on failure."""
    from teleclaude.core.voice_message_handler import transcribe_voice_with_retry

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        # Mock client that fails first, succeeds second
        mock_client = MagicMock()
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First attempt failed")
            mock_result = MagicMock()
            mock_result.text = "Success on retry"
            return mock_result

        mock_client.audio.transcriptions.create = mock_create

        result = await transcribe_voice_with_retry(audio_path, max_retries=1, client=mock_client)

        assert result == "Success on retry"
        assert call_count == 2  # 1 failure + 1 success
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_with_retry_returns_none_after_max_retries():
    """Test that retry function returns None after all retries fail."""
    from teleclaude.core.voice_message_handler import transcribe_voice_with_retry

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        # Mock client that always fails
        mock_client = MagicMock()
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("Always fails")

        mock_client.audio.transcriptions.create = mock_create

        result = await transcribe_voice_with_retry(audio_path, max_retries=2, client=mock_client)

        assert result is None
        assert call_count == 3  # 1 initial + 2 retries
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_rejects_no_active_process():
    """Test that handle_voice rejects when no process is running."""
    from teleclaude.core.events import VoiceEventContext
    from teleclaude.core.voice_message_handler import handle_voice

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        mock_send_feedback = AsyncMock(return_value="msg-123")

        # Mock session and db
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = False  # No active process

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            await handle_voice("test-session-123", audio_path, context, mock_send_feedback)

        # Verify rejection message sent
        mock_send_feedback.assert_called_once()
        call_args = mock_send_feedback.call_args[0]
        assert "requires an active process" in call_args[1]

        # Verify temp file cleaned up
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_rejects_no_output_message():
    """Test that handle_voice rejects when output message not ready."""
    from teleclaude.core.events import VoiceEventContext
    from teleclaude.core.voice_message_handler import handle_voice

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        mock_send_feedback = AsyncMock(return_value="msg-123")

        # Mock session with no output_message_id
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.origin_adapter = "telegram"
        mock_session.adapter_metadata.telegram.output_message_id = None

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = True  # Polling active

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            await handle_voice("test-session-123", audio_path, context, mock_send_feedback)

        # Verify rejection message sent
        mock_send_feedback.assert_called_once()
        call_args = mock_send_feedback.call_args[0]
        assert "not ready" in call_args[1]

    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_forwards_transcription_to_process():
    """Test that handle_voice forwards transcribed text to running process."""
    from teleclaude.core.events import VoiceEventContext
    from teleclaude.core.voice_message_handler import handle_voice

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        mock_send_feedback = AsyncMock(return_value="msg-123")

        # Mock session with output_message_id
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.origin_adapter = "telegram"
        mock_session.tmux_session_name = "tc_test"
        mock_session.adapter_metadata.telegram.output_message_id = "output-456"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
            patch("teleclaude.core.voice_message_handler.db.update_last_activity", new_callable=AsyncMock),
            patch(
                "teleclaude.core.voice_message_handler.transcribe_voice_with_retry",
                new_callable=AsyncMock,
            ) as mock_transcribe,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.send_keys",
                new_callable=AsyncMock,
            ) as mock_send_keys,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = True
            mock_transcribe.return_value = "Transcribed text"
            mock_send_keys.return_value = True

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            await handle_voice("test-session-123", audio_path, context, mock_send_feedback)

        # Verify transcription forwarded to terminal
        mock_send_keys.assert_called_once()
        call_args = mock_send_keys.call_args[0]
        assert call_args[0] == "tc_test"
        assert call_args[1] == "Transcribed text"

    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_transcribes_without_feedback_channel():
    """Test that handle_voice still transcribes when feedback can't be sent."""
    from teleclaude.core.events import VoiceEventContext
    from teleclaude.core.voice_message_handler import handle_voice

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        mock_send_feedback = AsyncMock(return_value=None)

        # Mock session with output_message_id
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.origin_adapter = "redis"
        mock_session.tmux_session_name = "tc_test"
        mock_session.adapter_metadata.telegram.output_message_id = "output-456"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
            patch("teleclaude.core.voice_message_handler.db.update_last_activity", new_callable=AsyncMock),
            patch(
                "teleclaude.core.voice_message_handler.transcribe_voice_with_retry",
                new_callable=AsyncMock,
            ) as mock_transcribe,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.send_keys",
                new_callable=AsyncMock,
            ) as mock_send_keys,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = True
            mock_transcribe.return_value = "Transcribed text"
            mock_send_keys.return_value = True

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            await handle_voice("test-session-123", audio_path, context, mock_send_feedback)

        # Verify transcription forwarded to terminal even without feedback
        mock_send_keys.assert_called_once()
        call_args = mock_send_keys.call_args[0]
        assert call_args[0] == "tc_test"
        assert call_args[1] == "Transcribed text"

        # Verify temp file cleaned up
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_cleans_up_temp_file_on_error():
    """Test that handle_voice cleans up temp file on transcription failure."""
    from teleclaude.core.events import VoiceEventContext
    from teleclaude.core.voice_message_handler import handle_voice

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        mock_send_feedback = AsyncMock(return_value="msg-123")

        # Mock session with output_message_id
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.origin_adapter = "telegram"
        mock_session.adapter_metadata.telegram.output_message_id = "output-456"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.terminal_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
            patch(
                "teleclaude.core.voice_message_handler.transcribe_voice_with_retry",
                new_callable=AsyncMock,
            ) as mock_transcribe,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = True
            mock_transcribe.return_value = None  # Transcription failed

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            await handle_voice("test-session-123", audio_path, context, mock_send_feedback)

        # Verify error message sent
        assert mock_send_feedback.call_count >= 2  # "Transcribing..." + error
        last_call = mock_send_feedback.call_args_list[-1]
        assert "failed" in last_call[0][1].lower()

        # Verify temp file cleaned up
        assert not Path(audio_path).exists()

    finally:
        Path(audio_path).unlink(missing_ok=True)
