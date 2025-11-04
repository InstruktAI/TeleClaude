"""Test voice message handling."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import voice_handler
from teleclaude.core.voice_handler import init_voice_handler, transcribe_voice, transcribe_voice_with_retry


async def test_voice_transcription():
    """Test voice transcription with direct injection (no patching)."""
    print("Testing voice transcription...")

    # Create a temporary audio file (empty is fine for testing)
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as temp_file:
        temp_file.write(b"fake audio data")
        audio_file_path = temp_file.name

    try:
        # Create mock client directly (no patching!)
        mock_client = MagicMock()

        # Mock the transcription response
        mock_transcript = MagicMock()
        mock_transcript.text = "list files in home directory"

        # Mock the async create method
        mock_create = AsyncMock(return_value=mock_transcript)
        mock_client.audio.transcriptions.create = mock_create

        # Test transcription with direct injection
        result = await transcribe_voice(audio_file_path, client=mock_client)

        # Verify result
        assert result == "list files in home directory", f"Expected 'list files in home directory', got '{result}'"
        print(f"✓ Transcription result: '{result}'")

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]
        assert call_args["model"] == "whisper-1", "Expected model 'whisper-1'"
        print("✓ API called with correct parameters")

    finally:
        # Clean up temp file
        Path(audio_file_path).unlink(missing_ok=True)

    print("\n✓ Voice transcription test passed!")


async def test_voice_transcription_with_retry():
    """Test voice transcription with retry logic."""
    print("\nTesting voice transcription with retry...")

    # Create a temporary audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as temp_file:
        temp_file.write(b"fake audio data")
        audio_file_path = temp_file.name

    try:
        # Create mock client directly
        mock_client = MagicMock()

        # Mock failure on first call, success on second
        mock_transcript = MagicMock()
        mock_transcript.text = "hello world"

        call_count = 0

        async def mock_create_with_retry(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("API error")
            return mock_transcript

        mock_client.audio.transcriptions.create = mock_create_with_retry

        # Test transcription with retry using direct injection
        result = await transcribe_voice_with_retry(audio_file_path, max_retries=1, client=mock_client)

        # Verify result
        assert result == "hello world", f"Expected 'hello world', got '{result}'"
        assert call_count == 2, f"Expected 2 API calls, got {call_count}"
        print(f"✓ Transcription succeeded after retry (attempts: {call_count})")

    finally:
        # Clean up temp file
        Path(audio_file_path).unlink(missing_ok=True)

    print("✓ Voice transcription retry test passed!")


async def test_voice_transcription_failure():
    """Test voice transcription failure after all retries."""
    print("\nTesting voice transcription failure after retries...")

    # Create a temporary audio file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as temp_file:
        temp_file.write(b"fake audio data")
        audio_file_path = temp_file.name

    try:
        # Create mock client directly
        mock_client = MagicMock()

        # Mock failure on all calls
        call_count = 0

        async def mock_create_always_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("API error")

        mock_client.audio.transcriptions.create = mock_create_always_fail

        # Test transcription with retry using direct injection
        result = await transcribe_voice_with_retry(audio_file_path, max_retries=1, client=mock_client)

        # Verify result is None (all retries failed)
        assert result is None, f"Expected None, got '{result}'"
        assert call_count == 2, f"Expected 2 API calls (1 initial + 1 retry), got {call_count}"
        print(f"✓ Transcription correctly failed after {call_count} attempts")

    finally:
        # Clean up temp file
        Path(audio_file_path).unlink(missing_ok=True)

    print("✓ Voice transcription failure test passed!")


class TestInitVoiceHandler:
    """Test init_voice_handler function."""

    @pytest.fixture(autouse=True)
    def reset_client(self):
        """Reset global client before each test."""
        voice_handler._openai_client = None
        yield
        voice_handler._openai_client = None

    def test_init_with_api_key(self):
        """Test initialization with API key provided."""
        init_voice_handler(api_key="test-key-123")
        assert voice_handler._openai_client is not None

    def test_init_with_env_var(self):
        """Test initialization with OPENAI_API_KEY environment variable."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key-456"}):
            init_voice_handler()
            assert voice_handler._openai_client is not None

    def test_init_already_initialized_raises_error(self):
        """Test that initializing twice raises RuntimeError."""
        init_voice_handler(api_key="test-key-1")

        with pytest.raises(RuntimeError, match="Voice handler already initialized"):
            init_voice_handler(api_key="test-key-2")

    def test_init_no_api_key_raises_error(self):
        """Test that missing API key raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="OPENAI_API_KEY not found"):
                init_voice_handler()


@pytest.mark.asyncio
class TestTranscribeVoice:
    """Test transcribe_voice function."""

    async def test_transcribe_without_client_raises_error(self):
        """Test that transcribing without initialized client raises RuntimeError."""
        # Reset global client
        voice_handler._openai_client = None

        with pytest.raises(RuntimeError, match="Voice handler not initialized"):
            await transcribe_voice("/tmp/audio.ogg")

    async def test_transcribe_nonexistent_file_raises_error(self):
        """Test that transcribing non-existent file raises FileNotFoundError."""
        mock_client = MagicMock()

        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            await transcribe_voice("/nonexistent/path/audio.ogg", client=mock_client)

    async def test_transcribe_with_language_parameter(self):
        """Test transcription with language parameter."""
        # Create temporary audio file
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as temp_file:
            temp_file.write(b"fake audio data")
            audio_file_path = temp_file.name

        try:
            # Create mock client
            mock_client = MagicMock()
            mock_transcript = MagicMock()
            mock_transcript.text = "transcribed text"
            mock_create = AsyncMock(return_value=mock_transcript)
            mock_client.audio.transcriptions.create = mock_create

            # Test with language parameter
            result = await transcribe_voice(audio_file_path, language="es", client=mock_client)

            # Verify language parameter passed
            assert result == "transcribed text"
            call_args = mock_create.call_args[1]
            assert call_args["language"] == "es"

        finally:
            Path(audio_file_path).unlink(missing_ok=True)


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Voice Message Handling Tests")
    print("=" * 60)

    await test_voice_transcription()
    await test_voice_transcription_with_retry()
    await test_voice_transcription_failure()

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
