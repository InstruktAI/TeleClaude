"""Unit tests for voice message handler."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import voice_message_handler
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.voice_message_handler import (
    handle_voice,
    transcribe_voice,
    transcribe_voice_with_retry,
)

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")


@pytest.fixture(autouse=True)
def reset_voice_handler():
    """Paranoid reset of voice handler module state before each test."""

    voice_message_handler._openai_client = None
    yield
    voice_message_handler._openai_client = None


def test_init_voice_handler_initializes_client():
    """Paranoid test that init_voice_handler creates OpenAI client."""

    calls = []

    def record_openai(*args, **kwargs):
        calls.append((args, kwargs))
        return MagicMock()

    with patch("teleclaude.core.voice_message_handler.AsyncOpenAI", new=record_openai):
        voice_message_handler.init_voice_handler(api_key="test-api-key")

        assert calls == [((), {"api_key": "test-api-key"})]
        assert voice_message_handler._openai_client is not None


def test_init_voice_handler_is_idempotent():
    """Paranoid test that init_voice_handler is safe to call multiple times (idempotent)."""

    calls = []

    def record_openai(*args, **kwargs):
        calls.append((args, kwargs))
        return MagicMock()

    with patch("teleclaude.core.voice_message_handler.AsyncOpenAI", new=record_openai):
        # First call initializes
        voice_message_handler.init_voice_handler(api_key="test-api-key")
        assert len(calls) == 1

        # Second call is a no-op (idempotent)
        voice_message_handler.init_voice_handler(api_key="another-key")
        assert len(calls) == 1  # Still only called once


def test_init_voice_handler_requires_api_key():
    """Paranoid test that init_voice_handler requires API key."""

    # Clear environment variable
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            voice_message_handler.init_voice_handler()


@pytest.mark.asyncio
async def test_transcribe_voice_calls_whisper_api():
    """Paranoid test that transcribe_voice calls Whisper API."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        # Create mock client
        mock_client = MagicMock()
        mock_transcript = MagicMock()
        mock_transcript.text = "Hello world"
        calls = []

        async def record_create(**kwargs):
            calls.append(kwargs)
            return mock_transcript

        mock_client.audio.transcriptions.create = record_create

        result = await transcribe_voice(audio_path, client=mock_client)

        assert result == "Hello world"
        assert len(calls) == 1
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_handles_file_not_found():
    """Paranoid test that transcribe_voice raises FileNotFoundError."""

    mock_client = MagicMock()

    with pytest.raises(FileNotFoundError):
        await transcribe_voice("/nonexistent/audio.ogg", client=mock_client)


@pytest.mark.asyncio
async def test_transcribe_voice_with_retry_retries_once():
    """Paranoid test that transcribe_voice_with_retry retries once on failure."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        # Mock client that fails first, succeeds second
        mock_client = MagicMock()
        attempts = []

        async def mock_create(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise Exception("First attempt failed")
            mock_result = MagicMock()
            mock_result.text = "Success on retry"
            return mock_result

        mock_client.audio.transcriptions.create = mock_create

        result = await transcribe_voice_with_retry(audio_path, max_retries=1, client=mock_client)

        assert result == "Success on retry"
        assert len(attempts) == 2  # 1 failure + 1 success
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_with_retry_returns_none_after_max_retries():
    """Paranoid test that retry function returns None after all retries fail."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        # Mock client that always fails
        mock_client = MagicMock()
        attempts = []

        async def mock_create(**kwargs):
            attempts.append(kwargs)
            raise Exception("Always fails")

        mock_client.audio.transcriptions.create = mock_create

        result = await transcribe_voice_with_retry(audio_path, max_retries=2, client=mock_client)

        assert result is None
        assert len(attempts) == 3  # 1 initial + 2 retries
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_rejects_no_active_process():
    """Paranoid test that handle_voice rejects when no process is running."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

        # Mock session and db
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.tmux_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = False  # No active process

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        # Verify rejection message sent
        assert len(sent) == 1
        assert "requires an active process" in sent[0][1]
        assert result is None

        # Verify temp file cleaned up
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_returns_none_when_session_missing():
    """Paranoid test that handle_voice returns None when session is missing."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
        ):
            mock_get.return_value = None

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        assert result is None
        assert sent == []

    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_forwards_transcription_to_process():
    """Paranoid test that handle_voice returns transcribed text for message pipeline."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

        # Mock session with tmux name
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.tmux_session_name = "tc_test"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.tmux_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
            patch(
                "teleclaude.core.voice_message_handler.transcribe_voice_with_retry",
                new_callable=AsyncMock,
            ) as mock_transcribe,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = True
            mock_transcribe.return_value = "Transcribed text"
            mock_delete = AsyncMock()

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice(
                "test-session-123",
                audio_path,
                context,
                record_send_message,
                delete_message=mock_delete,
            )

        assert result == "Transcribed text"
        assert mock_delete.call_args == (("test-session-123", "msg-123"), {})

    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_transcribes_without_notice_channel():
    """Paranoid test that handle_voice still transcribes when notice can't be sent."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return None

        # Mock session with tmux name
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.tmux_session_name = "tc_test"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.tmux_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
            patch(
                "teleclaude.core.voice_message_handler.transcribe_voice_with_retry",
                new_callable=AsyncMock,
            ) as mock_transcribe,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = True
            mock_transcribe.return_value = "Transcribed text"

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        assert result == "Transcribed text"

        # Verify temp file cleaned up
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_cleans_up_temp_file_on_error():
    """Paranoid test that handle_voice cleans up temp file on transcription failure."""

    # Create temp audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

        # Mock session with tmux name
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.tmux_session_name = "tc_test"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.tmux_bridge.is_process_running", new_callable=AsyncMock
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
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        # Verify error message sent
        assert len(sent) >= 2  # "Transcribing..." + error
        assert "failed" in sent[-1][1].lower()
        assert result is None

        # Verify temp file cleaned up
        assert not Path(audio_path).exists()

    finally:
        Path(audio_path).unlink(missing_ok=True)
