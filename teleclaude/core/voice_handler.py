"""Voice message handler using OpenAI Whisper API."""

import logging
import os
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class VoiceHandler:
    """Handles voice message transcription using OpenAI Whisper API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize voice handler.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment or provided")

        self.client = AsyncOpenAI(api_key=self.api_key)
        logger.info("VoiceHandler initialized")

    async def transcribe(self, audio_file_path: str, language: Optional[str] = None) -> str:
        """Transcribe audio file using Whisper API.

        Args:
            audio_file_path: Path to audio file
            language: Optional language code (e.g., 'en', 'es'). If None, auto-detect.

        Returns:
            Transcribed text

        Raises:
            Exception: If transcription fails
        """
        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        logger.info("Transcribing audio file: %s", audio_file_path)

        try:
            with open(audio_file_path, "rb") as audio_file:
                # Call Whisper API
                params = {
                    "model": "whisper-1",
                    "file": audio_file,
                }
                if language:
                    params["language"] = language

                transcript = await self.client.audio.transcriptions.create(**params)

            transcribed_text = transcript.text.strip()
            logger.info("Transcription successful: '%s...'", transcribed_text[:100])
            return transcribed_text

        except Exception as e:
            logger.error("Transcription failed: %s", e)
            raise

    async def transcribe_with_retry(
        self, audio_file_path: str, language: Optional[str] = None, max_retries: int = 1
    ) -> Optional[str]:
        """Transcribe audio with retry logic.

        Args:
            audio_file_path: Path to audio file
            language: Optional language code
            max_retries: Maximum number of retry attempts (default: 1, total 2 attempts)

        Returns:
            Transcribed text or None if all attempts fail
        """
        for attempt in range(max_retries + 1):
            try:
                return await self.transcribe(audio_file_path, language)
            except Exception as e:
                if attempt < max_retries:
                    logger.warning("Transcription attempt %d failed, retrying: %s", attempt + 1, e)
                else:
                    logger.error("Transcription failed after %d attempts: %s", max_retries + 1, e)
        return None  # All attempts failed
