"""Voice message handler using OpenAI Whisper API.

This module provides voice transcription functionality using OpenAI's Whisper API.
Uses module-level state for the OpenAI client (singleton pattern).
"""

import logging
import os
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Module-level state
_openai_client: Optional[AsyncOpenAI] = None


def init_voice_handler(api_key: Optional[str] = None) -> None:
    """Initialize OpenAI client for voice transcription.

    Args:
        api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)

    Raises:
        RuntimeError: If voice handler is already initialized
        ValueError: If API key is not provided or found in environment
    """
    global _openai_client

    if _openai_client is not None:
        raise RuntimeError("Voice handler already initialized")

    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_api_key:
        raise ValueError("OPENAI_API_KEY not found in environment or provided")

    _openai_client = AsyncOpenAI(api_key=resolved_api_key)
    logger.info("Voice handler initialized")


async def transcribe_voice(
    audio_file_path: str,
    language: Optional[str] = None,
    client: Optional[AsyncOpenAI] = None,
) -> str:
    """Transcribe audio file using Whisper API.

    Args:
        audio_file_path: Path to audio file
        language: Optional language code (e.g., 'en', 'es'). If None, auto-detect.
        client: Optional OpenAI client (for testing - uses global if not provided)

    Returns:
        Transcribed text

    Raises:
        RuntimeError: If voice handler is not initialized
        FileNotFoundError: If audio file does not exist
        Exception: If transcription fails
    """
    # Use injected client OR fallback to global
    resolved_client = client if client is not None else _openai_client

    if resolved_client is None:
        raise RuntimeError("Voice handler not initialized. Call init_voice_handler() first.")

    logger.info("=== TRANSCRIBE CALLED ===")
    logger.info("Audio file path: %s", audio_file_path)
    logger.info("Language: %s", language or "auto-detect")

    audio_path = Path(audio_file_path)
    if not audio_path.exists():
        logger.error("✗ Audio file not found: %s", audio_file_path)
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    file_size = audio_path.stat().st_size
    logger.info("Audio file exists: size=%s bytes", file_size)

    try:
        logger.info("Opening audio file for transcription...")
        with open(audio_file_path, "rb") as audio_file:
            # Call Whisper API
            params = {
                "model": "whisper-1",
                "file": audio_file,
            }
            if language:
                params["language"] = language

            logger.info(
                "Calling OpenAI Whisper API with model=%s, language=%s...",
                params["model"],
                params.get("language", "auto"),
            )
            transcript = await resolved_client.audio.transcriptions.create(**params)
            logger.info("✓ Whisper API call successful")

        transcribed_text = transcript.text.strip()
        logger.info(
            "✓ Transcription successful: '%s' (length: %s chars)", transcribed_text[:100], len(transcribed_text)
        )
        return transcribed_text

    except Exception as e:
        logger.error("✗ Transcription failed: %s", e, exc_info=True)
        raise


async def transcribe_voice_with_retry(
    audio_file_path: str,
    language: Optional[str] = None,
    max_retries: int = 1,
    client: Optional[AsyncOpenAI] = None,
) -> Optional[str]:
    """Transcribe audio with retry logic.

    Args:
        audio_file_path: Path to audio file
        language: Optional language code
        max_retries: Maximum number of retry attempts (default: 1, total 2 attempts)
        client: Optional OpenAI client (for testing - uses global if not provided)

    Returns:
        Transcribed text or None if all attempts fail
    """
    for attempt in range(max_retries + 1):
        try:
            return await transcribe_voice(audio_file_path, language, client=client)
        except Exception as e:
            if attempt < max_retries:
                logger.warning("Transcription attempt %d failed, retrying: %s", attempt + 1, e)
            else:
                logger.error("Transcription failed after %d attempts: %s", max_retries + 1, e)
    return None  # All attempts failed
