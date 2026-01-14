"""Voice message handling for terminal sessions.

Provides complete voice message functionality:
- OpenAI Whisper API integration (low-level transcription)
- Session business logic (validation, feedback, input forwarding)

Extracted from daemon.py to reduce file size and improve organization.
Refactored to be adapter-agnostic utility that accepts generic callbacks.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from instrukt_ai_logging import get_logger
from openai import AsyncOpenAI

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.models import MessageMetadata
from teleclaude.utils.markdown import escape_markdown_v2

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# ============================================================================
# LOW-LEVEL: OpenAI Whisper API Integration
# ============================================================================

# Module-level state
_openai_client: Optional[AsyncOpenAI] = None


def init_voice_handler(api_key: Optional[str] = None) -> None:
    """Initialize OpenAI client for voice transcription.

    Idempotent: safe to call multiple times (no-op if already initialized).

    Args:
        api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)

    Raises:
        ValueError: If API key is not provided or found in environment
    """
    global _openai_client

    if _openai_client is not None:
        logger.debug("Voice handler already initialized, skipping")
        return

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
            transcript = await resolved_client.audio.transcriptions.create(**params)  # type: ignore[misc, call-overload]
            logger.info("✓ Whisper API call successful")

        transcribed_text: str = str(transcript.text).strip()  # type: ignore[misc]
        logger.info(
            "✓ Transcription successful: '%s' (length: %s chars)",
            transcribed_text[:100],
            len(transcribed_text),
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


# ============================================================================
# HIGH-LEVEL: Session Business Logic
# ============================================================================


async def handle_voice(
    session_id: str,
    audio_path: str,
    context: VoiceEventContext,
    send_message: Callable[[str, str, MessageMetadata], Awaitable[Optional[str]]],
    delete_message: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> Optional[str]:
    """Handle voice message (adapter-agnostic utility).

    Args:
        session_id: Session ID
        audio_path: Path to downloaded audio file
        context: Typed voice event context
        send_message: Async function to send user feedback (session_id, message, append_to_existing)
    """
    logger.info("=== DAEMON HANDLE_VOICE CALLED ===")
    logger.info("Session ID: %s", session_id[:8])
    logger.info("Audio path: %s", audio_path)
    logger.info("Context: %s", context)
    logger.info("Voice message for session %s, duration: %ss", session_id[:8], context.duration)

    # Get session
    session = await db.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return None

    # Check if a process is currently running (foreground command != shell)
    is_process_running = await terminal_bridge.is_process_running(session.tmux_session_name)

    # Reject voice messages if no active process to send them to
    if not is_process_running:
        await send_message(
            session_id,
            "🎤 Voice input requires an active process (e.g., claude, vim)",
            MessageMetadata(),
        )
        # Clean up temp file
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file (rejected - no active process): %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
        return None

    # Voice message accepted - transcribe and forward through message pipeline.

    # Send transcribing status if feedback channel is available
    msg_id = await send_message(
        session_id,
        "🎤 Transcribing...",
        MessageMetadata(),
    )
    if msg_id is None:
        logger.info(
            "Feedback not sent for session %s (non-UI adapter or topic unavailable); continuing transcription",
            session_id[:8],
        )

    # Transcribe audio using Whisper
    text = await transcribe_voice_with_retry(audio_path)

    # Clean up temp file
    try:
        Path(audio_path).unlink()
        logger.debug("Cleaned up voice file: %s", audio_path)
    except Exception as e:
        logger.warning("Failed to clean up voice file %s: %s", audio_path, e)

    if not text:
        # Append error to existing message
        await send_message(
            session_id,
            "❌ Transcription failed. Please try again.",
            MessageMetadata(),
        )
        return None

    # Send transcribed text back to UI (quoted + italics)
    escaped_text = escape_markdown_v2(text)
    transcribed_message = f'*Transcribed text:*\n\n_"{escaped_text}"_'
    await send_message(
        session_id,
        transcribed_message,
        MessageMetadata(parse_mode="MarkdownV2"),
    )

    if msg_id is not None and delete_message is not None:
        try:
            await delete_message(session_id, msg_id)
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            logger.warning("Failed to delete transcribing message for session %s: %s", session_id[:8], exc)

    logger.debug("Transcribed voice input for session %s: %s", session_id[:8], text)
    return text
