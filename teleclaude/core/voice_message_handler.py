"""Voice message handling for tmux sessions.

Provides complete voice message functionality:
- STT backend chain (local Parakeet → cloud Whisper) with configurable priority
- Session business logic (validation, feedback, input forwarding)

Extracted from daemon.py to reduce file size and improve organization.
Refactored to be adapter-agnostic utility that accepts generic callbacks.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import (
    VOICE_TRANSCRIPTION_NOTICE_EDIT_MAX_CHARS,
    VOICE_TRANSCRIPTION_STATE_FAILED,
    VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
    VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
    VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
    VOICE_TRANSCRIPTION_TIMEOUT_S,
)
from teleclaude.core import tmux_bridge
from teleclaude.core.db import db
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.stt.backends import BACKENDS, STTBackend

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


def init_voice_handler(api_key: str | None = None) -> None:
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
    language: str | None = None,
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
    language: str | None = None,
    max_retries: int = 1,
) -> tuple[str | None, str | None]:
    """Transcribe audio with retry logic.

    Args:
        audio_file_path: Path to audio file
        language: Optional language code
        max_retries: Maximum number of retry attempts (default: 1, total 2 attempts)

    Returns:
        Tuple of (transcribed text, error reason). On success: (text, None).
        On failure: (None, reason).
    """
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            text = await asyncio.wait_for(
                transcribe_voice(audio_file_path, language),
                timeout=VOICE_TRANSCRIPTION_TIMEOUT_S,
            )
            return text, None
        except TimeoutError:
            last_error = f"Transcription timed out after {VOICE_TRANSCRIPTION_TIMEOUT_S:g} seconds"
            logger.error("Transcription timed out after %ss", VOICE_TRANSCRIPTION_TIMEOUT_S)
            return None, last_error
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


def _voice_context_value(context: VoiceEventContext | Mapping[str, object], key: str) -> object | None:
    if isinstance(context, Mapping):
        return context.get(key)
    return cast(object | None, getattr(context, key, None))


def _voice_context_int(context: VoiceEventContext | Mapping[str, object], key: str) -> int | None:
    value = _voice_context_value(context, key)
    if value is None:
        return None
    return int(str(value))


def _voice_context_float(context: VoiceEventContext | Mapping[str, object], key: str) -> float | None:
    value = _voice_context_value(context, key)
    if value is None:
        return None
    return float(str(value))


def _voice_context_str(context: VoiceEventContext | Mapping[str, object], key: str) -> str | None:
    value = _voice_context_value(context, key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _apply_transcription_reflection_metadata(
    metadata: MessageMetadata,
    session: Session,
    context: VoiceEventContext | Mapping[str, object],
) -> bool:
    origin = _voice_context_str(context, "origin")
    actor_name = _voice_context_str(context, "actor_name")
    actor_id = _voice_context_str(context, "actor_id")
    actor_avatar_url = _voice_context_str(context, "actor_avatar_url")

    if actor_name:
        metadata.reflection_actor_id = actor_id
        metadata.reflection_actor_name = actor_name
        metadata.reflection_actor_avatar_url = actor_avatar_url
        metadata.reflection_origin = origin
        return True

    if not origin:
        logger.warning(
            "Skipping voice transcription display for session %s because origin is missing", session.session_id
        )
        return False

    try:
        identity = get_identity_resolver().resolve(origin, session.get_origin_section(origin))
        resolved_name = identity.display_name
    except ValueError:
        logger.warning(
            "Skipping voice transcription display for session %s because actor identity is unresolved",
            session.session_id,
        )
        return False

    metadata.reflection_actor_id = identity.platform_user_id
    metadata.reflection_actor_name = resolved_name
    metadata.reflection_origin = origin
    return True


async def _resolve_voice_notice(
    *,
    session_id: str,
    message: str,
    metadata: MessageMetadata,
    send_message: Callable[[str, str, MessageMetadata], Awaitable[str | None]],
    edit_message: Callable[[str, str, str, MessageMetadata], Awaitable[bool]] | None,
    notice_message_id: str | None,
    delete_message: Callable[[str, str], Awaitable[None]] | None = None,
) -> None:
    if metadata.is_transcription:
        fallback_message_id = await send_message(session_id, message, metadata)
        if fallback_message_id is not None and notice_message_id is not None and delete_message is not None:
            try:
                await delete_message(session_id, notice_message_id)
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                logger.warning("Failed to delete unresolved voice notice for session %s: %s", session_id, exc)
        return

    if notice_message_id is not None and edit_message is not None:
        if len(message) <= VOICE_TRANSCRIPTION_NOTICE_EDIT_MAX_CHARS:
            edited = await edit_message(session_id, notice_message_id, message, metadata)
            if edited:
                return
            logger.warning(
                "Voice notice edit failed for session %s message %s; sending fallback notice",
                session_id,
                notice_message_id,
            )
        else:
            logger.info(
                "Voice notice for session %s exceeds edit budget (%d > %d); sending overflow fallback",
                session_id,
                len(message),
                VOICE_TRANSCRIPTION_NOTICE_EDIT_MAX_CHARS,
            )
    fallback_message_id = await send_message(session_id, message, metadata)
    if fallback_message_id is not None and notice_message_id is not None and delete_message is not None:
        try:
            await delete_message(session_id, notice_message_id)
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            logger.warning("Failed to delete unresolved voice notice for session %s: %s", session_id, exc)


async def handle_voice(
    session_id: str,
    audio_path: str,
    context: VoiceEventContext | Mapping[str, object],
    send_message: Callable[[str, str, MessageMetadata], Awaitable[str | None]],
    edit_message: Callable[[str, str, str, MessageMetadata], Awaitable[bool]] | None = None,
    delete_message: Callable[[str, str], Awaitable[None]] | None = None,
) -> str | None:
    """Handle voice message (adapter-agnostic utility).

    Args:
        session_id: Session ID
        audio_path: Path to downloaded audio file
        context: Typed voice event context
        send_message: Async function to send UI notices (session_id, message, metadata)
    """
    logger.info("=== DAEMON HANDLE_VOICE CALLED ===")
    logger.info("Session ID: %s", session_id)
    logger.info("Audio path: %s", audio_path)
    logger.info("Context: %s", context)
    logger.info("Voice message for session %s, duration: %ss", session_id, _voice_context_value(context, "duration"))

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
    recovered_transcription_id = _voice_context_int(context, "voice_transcription_id")
    msg_id = str(_voice_context_value(context, "notice_message_id") or "") or None
    if recovered_transcription_id is None:
        message_thread_id = _voice_context_value(context, "message_thread_id")
        actor_id = _voice_context_value(context, "actor_id")
        actor_name = _voice_context_value(context, "actor_name")
        actor_avatar_url = _voice_context_value(context, "actor_avatar_url")
        duration = _voice_context_float(context, "duration")
        transcription = await db.create_voice_transcription(
            session_id=session_id,
            audio_path=audio_path,
            origin=str(_voice_context_value(context, "origin") or ""),
            thread_id=str(message_thread_id) if message_thread_id is not None else None,
            actor_id=str(actor_id) if actor_id is not None else None,
            actor_name=str(actor_name) if actor_name is not None else None,
            actor_avatar_url=str(actor_avatar_url) if actor_avatar_url is not None else None,
            duration=duration,
            language=DEFAULT_TRANSCRIBE_LANGUAGE,
        )
    else:
        transcription = await db.get_voice_transcription(recovered_transcription_id)
        if transcription is None:
            logger.warning("Voice transcription row %s not found for recovery", recovered_transcription_id)
            return None

    if msg_id is None:
        # Send transcribing status if notice channel is available.
        msg_id = await send_message(
            session_id,
            "🎤 Transcribing...",
            MessageMetadata(parse_mode=None, cleanup_trigger="next_notice"),
        )
        if msg_id is None:
            logger.info(
                "Notice not sent for session %s (non-UI adapter or topic unavailable); continuing transcription",
                session_id,
            )
        elif transcription.id is not None:
            await db.set_voice_transcription_notice_message_id(transcription.id, msg_id)
    else:
        await _resolve_voice_notice(
            session_id=session_id,
            message="🎤 Retrying transcription after restart...",
            metadata=MessageMetadata(parse_mode=None),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
            notice_message_id=msg_id,
        )

    voice_state: str | None = None

    # Transcribe audio using STT backend chain
    if transcription.id is not None:
        await db.update_voice_transcription_state(transcription.id, VOICE_TRANSCRIPTION_STATE_IN_PROGRESS)
        voice_state = VOICE_TRANSCRIPTION_STATE_IN_PROGRESS
    try:
        text, error_reason = await transcribe_voice_with_retry(audio_path, language=DEFAULT_TRANSCRIBE_LANGUAGE)
    except asyncio.CancelledError:
        if transcription.id is not None and voice_state == VOICE_TRANSCRIPTION_STATE_IN_PROGRESS:
            await db.update_voice_transcription_state(transcription.id, VOICE_TRANSCRIPTION_STATE_INTERRUPTED)
            await asyncio.shield(
                _resolve_voice_notice(
                    session_id=session_id,
                    message="⚠️ Transcription interrupted by daemon restart - your message will retry on startup.",
                    metadata=MessageMetadata(parse_mode=None),
                    send_message=send_message,
                    edit_message=edit_message,
                    delete_message=delete_message,
                    notice_message_id=msg_id,
                )
            )
        raise

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
        if transcription.id is not None:
            await db.update_voice_transcription_state(
                transcription.id,
                VOICE_TRANSCRIPTION_STATE_FAILED,
                last_error=error_reason,
            )
            voice_state = VOICE_TRANSCRIPTION_STATE_FAILED
        await _resolve_voice_notice(
            session_id=session_id,
            message=failure_message,
            metadata=MessageMetadata(parse_mode=None),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
            notice_message_id=msg_id,
        )
        return None

    if transcription.id is not None:
        await db.update_voice_transcription_state(transcription.id, VOICE_TRANSCRIPTION_STATE_SUCCEEDED)
        voice_state = VOICE_TRANSCRIPTION_STATE_SUCCEEDED

    # Resolve the existing placeholder with the transcribed text.
    transcription_metadata = MessageMetadata(parse_mode=None, is_transcription=True, cleanup_trigger="next_turn")
    if not _apply_transcription_reflection_metadata(transcription_metadata, session, context):
        logger.debug("Transcribed voice input for session %s without UI transcription display", session_id)
        return text

    await _resolve_voice_notice(
        session_id=session_id,
        message=text,
        metadata=transcription_metadata,
        send_message=send_message,
        edit_message=edit_message,
        delete_message=delete_message,
        notice_message_id=msg_id,
    )

    logger.debug("Transcribed voice input for session %s: %s", session_id, text)
    return text
