"""Polling coordinator for terminal output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from teleclaude.core import output_message_manager, state_manager
from teleclaude.core.output_poller import (
    IdleDetected,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _is_ai_to_ai_session(topic_name: str) -> bool:
    """Check if topic matches AI-to-AI pattern: $X > $Y - {title}

    Args:
        topic_name: Topic/channel name from session

    Returns:
        True if AI-to-AI session, False otherwise
    """
    if not topic_name:
        return False
    # Match pattern: $CompName > $CompName - Title
    return bool(re.match(r"^\$\w+ > \$\w+ - .+$", topic_name))


async def _send_output_chunks_ai_mode(
    session_id: str,
    adapter: Any,
    full_output: str,
    session_manager: SessionManager,
) -> None:
    """Send output as sequential chunks for AI consumption.

    Uses adapter's max_message_length (platform-specific).
    No editing - each chunk is a new message.

    Args:
        session_id: Session ID
        adapter: Adapter instance (with get_max_message_length method)
        full_output: Complete output to send
        session_manager: Session manager instance
    """
    # Get adapter's platform-specific max message length
    chunk_size = adapter.get_max_message_length() - 100  # Reserve for markdown + markers

    # Split output into chunks
    chunks = [full_output[i : i + chunk_size] for i in range(0, len(full_output), chunk_size)]

    # Send each chunk as new message
    for idx, chunk in enumerate(chunks, 1):
        # Format with sequence marker
        message = f"```sh\n{chunk}\n```\n[Chunk {idx}/{len(chunks)}]"

        # Send as NEW message (don't edit)
        await adapter.send_message(session_id, message)

        # Small delay to preserve order (Telegram API constraint)
        await asyncio.sleep(0.1)

    # Mark completion (MCP streaming loop will detect and stop)
    await adapter.send_message(session_id, "[Output Complete]")


async def poll_and_send_output(
    session_id: str,
    tmux_session_name: str,
    session_manager: SessionManager,
    output_poller: OutputPoller,
    get_adapter_for_session: Callable[[str], Awaitable[Any]],
    get_output_file: Callable[[str], Path],
) -> None:
    """Poll terminal output and send to chat adapter.

    Pure orchestration - consumes events from poller, delegates to message manager.
    SINGLE RESPONSIBILITY: Owns the polling lifecycle for a session.

    Args:
        session_id: Session ID
        tmux_session_name: tmux session name
        session_manager: Session manager instance
        output_poller: Output poller instance
        get_adapter_for_session: Function to get adapter for session
        get_output_file: Function to get output file path for session
    """
    # GUARD: Prevent duplicate polling (check and add atomically before any await)
    if state_manager.is_polling(session_id):
        logger.warning(
            "Polling already active for session %s, ignoring duplicate request",
            session_id[:8],
        )
        return

    # Mark as active BEFORE any await (prevents race conditions)
    state_manager.mark_polling(session_id)

    # Get adapter for this session
    adapter = await get_adapter_for_session(session_id)

    # Get session to check topic type
    session = await session_manager.get_session(session_id)
    is_ai_session = _is_ai_to_ai_session(session.title if session else None)

    # Get output file and exit marker status
    output_file = get_output_file(session_id)
    # Check in-memory state for exit marker (set by send_keys / terminal_executor)
    # Default to False if not found (don't use output_message_id as fallback anymore)
    has_exit_marker = state_manager.get_exit_marker(session_id, False)

    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file, has_exit_marker):
            if isinstance(event, OutputChanged):
                if is_ai_session:
                    # AI mode: Send sequential chunks (no editing, no loss)
                    await _send_output_chunks_ai_mode(
                        event.session_id,
                        adapter,
                        event.output,
                        session_manager,
                    )
                else:
                    # Human mode: Edit same message (current behavior)
                    await output_message_manager.send_output_update(
                        event.session_id,
                        adapter,
                        event.output,
                        event.started_at,
                        event.last_changed_at,
                        session_manager,
                        max_message_length=3800,
                    )

                # Delete idle notification if one exists (output resumed)
                notification_id = await session_manager.get_idle_notification_message_id(event.session_id)
                if notification_id:
                    await adapter.delete_message(event.session_id, notification_id)
                    await session_manager.set_idle_notification_message_id(event.session_id, None)
                    logger.debug("Deleted idle notification %s for session %s", notification_id, event.session_id[:8])

            elif isinstance(event, IdleDetected):
                # Idle detected - send notification
                notification = (
                    f"⏸️ No output for {event.idle_seconds} seconds - " "process may be waiting or hung up, try cancel"
                )
                notification_id = await adapter.send_message(event.session_id, notification)
                if notification_id:
                    # Persist to DB (survives daemon restart)
                    await session_manager.set_idle_notification_message_id(event.session_id, notification_id)
                    logger.debug("Stored idle notification %s for session %s", notification_id, event.session_id[:8])

            elif isinstance(event, ProcessExited):
                # Process exited
                if event.exit_code is not None:
                    # Exit with code - send final message (edits existing message)
                    await output_message_manager.send_output_update(
                        event.session_id,
                        adapter,
                        event.final_output,
                        event.started_at,  # Use actual start time from poller
                        time.time(),
                        session_manager,
                        max_message_length=3800,
                        is_final=True,
                        exit_code=event.exit_code,
                    )
                    logger.info(
                        "Polling stopped for %s (exit code: %d), output file kept for downloads",
                        event.session_id[:8],
                        event.exit_code,
                    )
                else:
                    # Session died - send exit message
                    await output_message_manager.send_exit_message(
                        event.session_id, adapter, event.final_output, "✅ Process exited", session_manager
                    )
                    # Delete output file on session death
                    try:
                        if output_file.exists():
                            output_file.unlink()
                            logger.debug("Deleted output file for exited session %s", event.session_id[:8])
                    except Exception as e:
                        logger.warning("Failed to delete output file: %s", e)

    finally:
        # Cleanup
        state_manager.unmark_polling(session_id)
        state_manager.remove_exit_marker(session_id)
        state_manager.clear_pending_deletions(session_id)  # Clear any pending message deletions
        await session_manager.set_idle_notification_message_id(session_id, None)
        logger.debug("Polling ended for session %s", session_id[:8])
