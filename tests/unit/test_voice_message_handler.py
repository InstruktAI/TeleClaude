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


def test_init_voice_handler_sets_env_var():
    """init_voice_handler sets OPENAI_API_KEY for the Whisper backend."""
    with patch.dict("os.environ", {}, clear=True):
        voice_message_handler.init_voice_handler(api_key="test-api-key")
        assert os.environ.get("OPENAI_API_KEY") == "test-api-key"


def test_init_voice_handler_does_not_overwrite_existing_key():
    """init_voice_handler does not overwrite an existing OPENAI_API_KEY."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "existing-key"}):
        voice_message_handler.init_voice_handler(api_key="new-key")
        assert os.environ["OPENAI_API_KEY"] == "existing-key"


@pytest.mark.asyncio
async def test_transcribe_voice_uses_backend_chain():
    """transcribe_voice tries backends in order until one succeeds."""
    mock_backend = MagicMock()
    mock_backend.transcribe = AsyncMock(return_value="Hello world")

    with patch("teleclaude.core.voice_message_handler._get_service_chain", return_value=[("mock", mock_backend)]):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            result = await transcribe_voice(audio_path, language="en")
            assert result == "Hello world"
            mock_backend.transcribe.assert_called_once_with(audio_path, "en")
        finally:
            Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_falls_through_on_failure():
    """transcribe_voice falls through to next backend when first fails."""
    backend_a = MagicMock()
    backend_a.transcribe = AsyncMock(side_effect=RuntimeError("backend A down"))
    backend_b = MagicMock()
    backend_b.transcribe = AsyncMock(return_value="Fallback success")

    chain = [("a", backend_a), ("b", backend_b)]
    with patch("teleclaude.core.voice_message_handler._get_service_chain", return_value=chain):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            result = await transcribe_voice(audio_path)
            assert result == "Fallback success"
        finally:
            Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_raises_when_all_fail():
    """transcribe_voice raises RuntimeError when all backends fail."""
    backend = MagicMock()
    backend.transcribe = AsyncMock(side_effect=RuntimeError("nope"))

    with patch("teleclaude.core.voice_message_handler._get_service_chain", return_value=[("mock", backend)]):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            with pytest.raises(RuntimeError, match="All STT backends failed"):
                await transcribe_voice(audio_path)
        finally:
            Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_raises_when_no_backends():
    """transcribe_voice raises when no backends available."""
    with patch("teleclaude.core.voice_message_handler._get_service_chain", return_value=[]):
        with pytest.raises(RuntimeError, match="No STT backends available"):
            await transcribe_voice("/nonexistent.ogg")


@pytest.mark.asyncio
async def test_transcribe_voice_with_retry_retries_once():
    """transcribe_voice_with_retry retries on failure."""
    attempts = []
    mock_backend = MagicMock()

    async def mock_transcribe(path, lang=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("first fail")
        return "Success on retry"

    mock_backend.transcribe = mock_transcribe

    with patch("teleclaude.core.voice_message_handler._get_service_chain", return_value=[("mock", mock_backend)]):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            text, error = await transcribe_voice_with_retry(audio_path, max_retries=1)
            assert text == "Success on retry"
            assert error is None
            assert len(attempts) == 2
        finally:
            Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transcribe_voice_with_retry_returns_none_after_max_retries():
    """Retry function returns None after all retries fail."""
    mock_backend = MagicMock()
    mock_backend.transcribe = AsyncMock(side_effect=RuntimeError("Always fails"))

    with patch("teleclaude.core.voice_message_handler._get_service_chain", return_value=[("mock", mock_backend)]):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            text, error = await transcribe_voice_with_retry(audio_path, max_retries=2)
            assert text is None
            assert "Always fails" in (error or "")
        finally:
            Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_rejects_no_active_process():
    """handle_voice rejects when no process is running."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"

        with (
            patch("teleclaude.core.voice_message_handler.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.voice_message_handler.tmux_bridge.is_process_running", new_callable=AsyncMock
            ) as mock_polling,
        ):
            mock_get.return_value = mock_session
            mock_polling.return_value = False

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        assert len(sent) == 1
        assert "requires an active process" in sent[0][1]
        assert result is None
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_returns_none_when_session_missing():
    """handle_voice returns None when session is missing."""
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
    """handle_voice returns transcribed text for message pipeline."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

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
            mock_transcribe.return_value = ("Transcribed text", None)
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
    """handle_voice still transcribes when notice can't be sent."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return None

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
            mock_transcribe.return_value = ("Transcribed text", None)

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        assert result == "Transcribed text"
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_voice_cleans_up_temp_file_on_error():
    """handle_voice cleans up temp file on transcription failure."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as f:
        f.write(b"fake audio data")
        audio_path = f.name

    try:
        sent = []

        async def record_send_message(session, text, *args, **kwargs):
            sent.append((session, text))
            return "msg-123"

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
            mock_transcribe.return_value = (None, "insufficient_quota")

            context = VoiceEventContext(session_id="test-session-123", file_path=audio_path, duration=5.0)
            result = await handle_voice("test-session-123", audio_path, context, record_send_message)

        assert len(sent) >= 2  # "Transcribing..." + error
        assert "transcription failed" in sent[-1][1].lower()
        assert "insufficient_quota" in sent[-1][1]
        assert result is None
        assert not Path(audio_path).exists()
    finally:
        Path(audio_path).unlink(missing_ok=True)
