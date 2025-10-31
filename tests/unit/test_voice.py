"""Test voice message handling."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from teleclaude.core.voice_handler import VoiceHandler


async def test_voice_transcription():
    """Test voice transcription with mocked OpenAI API."""
    print("Testing voice transcription...")

    # Create a temporary audio file (empty is fine for testing)
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as temp_file:
        temp_file.write(b"fake audio data")
        audio_file_path = temp_file.name

    try:
        # Mock the OpenAI client
        with patch("teleclaude.core.voice_handler.AsyncOpenAI") as mock_openai_class:
            # Create mock client instance
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client

            # Mock the transcription response
            mock_transcript = MagicMock()
            mock_transcript.text = "list files in home directory"

            # Mock the async create method
            mock_create = AsyncMock(return_value=mock_transcript)
            mock_client.audio.transcriptions.create = mock_create

            # Initialize voice handler
            voice_handler = VoiceHandler(api_key="test_key")

            # Test transcription
            result = await voice_handler.transcribe(audio_file_path)

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
        # Mock the OpenAI client
        with patch("teleclaude.core.voice_handler.AsyncOpenAI") as mock_openai_class:
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client

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

            # Initialize voice handler
            voice_handler = VoiceHandler(api_key="test_key")

            # Test transcription with retry
            result = await voice_handler.transcribe_with_retry(audio_file_path, max_retries=1)

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
        # Mock the OpenAI client
        with patch("teleclaude.core.voice_handler.AsyncOpenAI") as mock_openai_class:
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client

            # Mock failure on all calls
            call_count = 0

            async def mock_create_always_fail(**kwargs):
                nonlocal call_count
                call_count += 1
                raise Exception("API error")

            mock_client.audio.transcriptions.create = mock_create_always_fail

            # Initialize voice handler
            voice_handler = VoiceHandler(api_key="test_key")

            # Test transcription with retry
            result = await voice_handler.transcribe_with_retry(audio_file_path, max_retries=1)

            # Verify result is None (all retries failed)
            assert result is None, f"Expected None, got '{result}'"
            assert call_count == 2, f"Expected 2 API calls (1 initial + 1 retry), got {call_count}"
            print(f"✓ Transcription correctly failed after {call_count} attempts")

    finally:
        # Clean up temp file
        Path(audio_file_path).unlink(missing_ok=True)

    print("✓ Voice transcription failure test passed!")


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
