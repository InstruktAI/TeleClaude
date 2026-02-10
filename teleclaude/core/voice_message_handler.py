"""Voice message handling for tmux sessions.

Provides complete voice message functionality:
- STT backend chain (local Parakeet → cloud Whisper) with configurable priority
- Session business logic (validation, feedback, input forwarding)

Extracted from daemon.py to reduce file size and improve organization.
Refactored to be adapter-agnostic utility that accepts generic callbacks.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import tmux_bridge
from teleclaude.core.db import db
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.models import MessageMetadata
from teleclaude.stt.backends import BACKENDS, STTBackend
from teleclaude.utils.markdown import escape_markdown_v2

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)
DEFAULT_TRANSCRIBE_LANGUAGE = "en"

# ============================================================================
# LOW-LEVEL: STT Backend Chain
# ============================================================================


def _get_service_chain() -> list[tuple[str, STTBackend]]:
    """Build ordered list of STT backends from config priority."""
    stt_cfg = config.stt
    if stt_cfg and stt_cfg.enabled and stt_cfg.service_priority:
        chain = []
        for name in stt_cfg.service_priority:
            # Check if service is enabled in config
            if stt_cfg.services:
                service_cfg = stt_cfg.services.get(name)
                if service_cfg and not service_cfg.enabled:
                    continue
            backend = BACKENDS.get(name)
            if backend:
                chain.append((name, backend))
        return chain

    # Default fallback: all registered backends
    return list(BACKENDS.items())


def init_voice_handler(api_key: Optional[str] = None) -> None:
    """Initialize voice handler.

    Kept for backward compatibility with daemon lifecycle.
    The OpenAI backend now lazy-inits from OPENAI_API_KEY env var,
    so this is effectively a no-op unless you need to set the key explicitly.

    Args:
        api_key: OpenAI API key (sets env var for the Whisper backend)
    """
    if api_key:
        os.environ.setdefault("OPENAI_API_KEY", api_key)
    logger.info("Voice handler initialized (STT backends: %s)", list(BACKENDS.keys()))


async def transcribe_voice(
    audio_file_path: str,
    language: Optional[str] = None,
) -> str:
    """Transcribe audio file using STT backend chain.

    Tries each backend in priority order until one succeeds.

    Args:
        audio_file_path: Path to audio file
        language: Optional language code (e.g., 'en'). Some backends ignore this.

    Returns:
        Transcribed text

    Raises:
        RuntimeError: If all backends fail
    """
    chain = _get_service_chain()
    if not chain:
        raise RuntimeError("No STT backends available")

    errors: list[str] = []
    for name, backend in chain:
        try:
            text = await backend.transcribe(audio_file_path, language)
            if text:
                logger.info("STT transcribed via %s: %d chars", name, len(text))
                return text
        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning("STT backend %s failed: %s", name, e)

    raise RuntimeError(f"All STT backends failed: {'; '.join(errors)}")


async def transcribe_voice_with_retry(
    audio_file_path: str,
    language: Optional[str] = None,
    max_retries: int = 1,
) -> tuple[Optional[str], Optional[str]]:
    """Transcribe audio with retry logic.

    Args:
        audio_file_path: Path to audio file
        language: Optional language code
        max_retries: Maximum number of retry attempts (default: 1, total 2 attempts)

    Returns:
        Tuple of (transcribed text, error reason). On success: (text, None).
        On failure: (None, reason).
    """
    last_error: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            text = await transcribe_voice(audio_file_path, language)
            return text, None
        except Exception as e:
            last_error = str(e).strip() or e.__class__.__name__
            if attempt < max_retries:
                logger.warning("Transcription attempt %d failed, retrying: %s", attempt + 1, e)
            else:
                logger.error("Transcription failed after %d attempts: %s", max_retries + 1, e)
    return None, last_error  # All attempts failed


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
        send_message: Async function to send UI notices (session_id, message, metadata)
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
    is_process_running = await tmux_bridge.is_process_running(session.tmux_session_name)

    # Reject voice messages if no active process to send them to
    if not is_process_running:
        await send_message(
            session_id,
            "🎤 Voice input requires an active process (e.g., claude, vim)",
            MessageMetadata(parse_mode=None),
        )
        # Clean up temp file
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file (rejected - no active process): %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
        return None

    # Voice message accepted - transcribe and forward through message pipeline.

    # Send transcribing status if notice channel is available
    msg_id = await send_message(
        session_id,
        "🎤 Transcribing...",
        MessageMetadata(parse_mode=None),
    )
    if msg_id is None:
        logger.info(
            "Notice not sent for session %s (non-UI adapter or topic unavailable); continuing transcription",
            session_id[:8],
        )

    # Transcribe audio using STT backend chain
    text, error_reason = await transcribe_voice_with_retry(audio_path, language=DEFAULT_TRANSCRIBE_LANGUAGE)

    # Clean up temp file
    try:
        Path(audio_path).unlink()
        logger.debug("Cleaned up voice file: %s", audio_path)
    except Exception as e:
        logger.warning("Failed to clean up voice file %s: %s", audio_path, e)

    if not text:
        failure_message = "❌ Transcription failed. Please try again."
        if error_reason:
            failure_message = f"❌ Transcription failed: {error_reason}"
        # Append error to existing message
        await send_message(
            session_id,
            failure_message,
            MessageMetadata(parse_mode=None),
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
