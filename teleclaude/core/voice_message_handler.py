"""Voice message handling for terminal sessions.

Extracted from daemon.py to reduce file size and improve organization.
Handles voice message validation, transcription, and input forwarding to active processes.
"""

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

from teleclaude.core import (
    output_message_manager,
    terminal_bridge,
    ux_state,
)
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.voice_handler import transcribe_voice_with_retry

logger = logging.getLogger(__name__)


async def handle_voice(
    session_id: str,
    audio_path: str,
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[Any]],
    get_output_file: Callable[[str], Path],
) -> None:
    """Handle incoming voice messages.

    Args:
        session_id: Session ID
        audio_path: Path to downloaded audio file
        context: Platform-specific context (includes duration, user_id, etc.)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        get_output_file: Function to get output file path for session
    """
    logger.info("=== DAEMON HANDLE_VOICE CALLED ===")
    logger.info("Session ID: %s", session_id[:8])
    logger.info("Audio path: %s", audio_path)
    logger.info("Context: %s", context)
    logger.info("Voice message for session %s, duration: %ss", session_id[:8], context.get("duration"))

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Get adapter for sending messages
    adapter = await get_adapter_for_session(session_id)

    # Check if a process is currently running (polling active)
    is_process_running = await session_manager.is_polling(session_id)

    # Reject voice messages if no active process to send them to
    if not is_process_running:
        await adapter.send_message(session_id, "🎤 Voice input requires an active process (e.g., claude, vim)")
        # Clean up temp file
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file (rejected - no active process): %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
        return

    # Voice message accepted - transcribe and send to active process
    output_file = get_output_file(session_id)

    # Check if output message exists (polling may have just started)
    session_data = await ux_state.get_session(session_id)
    current_message_id = session_data.get("output_message_id")
    if current_message_id is None:
        logger.warning("No output message yet for session %s, polling may have just started", session_id[:8])
        # Send rejection message
        await adapter.send_message(
            session_id, "⚠️ Voice input unavailable - output message not ready yet (try again in 1-2 seconds)"
        )
        # Clean up temp file
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file (no message_id yet): %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
        return

    # Send transcribing status (append to existing output)
    msg_id = await output_message_manager.send_status_message(
        session_id,
        adapter,
        "🎤 Transcribing...",
        session_manager,
        append_to_existing=True,
        output_file_path=str(output_file),
    )
    if msg_id is None:
        logger.info("Topic deleted for session %s, skipping transcription", session_id[:8])
        # Clean up temp file before returning
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file: %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
        return

    # Transcribe audio using Whisper
    transcribed_text = await transcribe_voice_with_retry(audio_path)

    # Clean up temp file
    try:
        Path(audio_path).unlink()
        logger.debug("Cleaned up voice file: %s", audio_path)
    except Exception as e:
        logger.warning("Failed to clean up voice file %s: %s", audio_path, e)

    if not transcribed_text:
        # Append error to existing message
        await output_message_manager.send_status_message(
            session_id,
            adapter,
            "❌ Transcription failed. Please try again.",
            session_manager,
            append_to_existing=True,
            output_file_path=str(output_file),
        )
        return

    # Send transcribed text as input to the running process
    logger.debug("Sending transcribed text as input to session %s: %s", session_id[:8], transcribed_text)
    success = await terminal_bridge.send_keys(
        session.tmux_session_name,
        transcribed_text,
        append_exit_marker=False,  # Never append exit marker - we're sending input to a running process
    )

    if not success:
        logger.error("Failed to send transcribed input to session %s", session_id[:8])
        await adapter.send_message(session_id, "❌ Failed to send input to terminal")
        return

    # Update activity
    await session_manager.update_last_activity(session_id)

    # Voice input sent to running process - existing poll will capture output
    logger.debug("Voice input sent to running process in session %s, existing poll will capture output", session_id[:8])
