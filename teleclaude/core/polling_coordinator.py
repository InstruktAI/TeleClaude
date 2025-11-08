"""Polling coordinator for terminal output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.output_poller import (
    IdleDetected,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


def _is_ai_to_ai_session(session: Session) -> bool:
    """Check if session is AI-to-AI via metadata flag.

    Args:
        session: Session object with adapter_metadata

    Returns:
        True if AI-to-AI session, False otherwise
    """
    if not session or not session.adapter_metadata:
        return False
    # Check metadata flag (set by teleclaude__start_session)
    return bool(session.adapter_metadata.get("is_ai_to_ai", False))


async def _send_output_chunks_ai_mode(
    session_id: str,
    adapter_client: "AdapterClient",
    full_output: str,
) -> None:
    """Send output as sequential chunks for AI consumption.

    No formatting - sends raw output chunks. Adapter handles platform-specific formatting.

    Args:
        session_id: Session ID
        adapter_client: AdapterClient instance for message sending
        full_output: Complete output to send
    """
    # Conservative chunk size (most platforms support at least 4000 chars)
    chunk_size = 3900

    # Split output into chunks
    chunks = [full_output[i : i + chunk_size] for i in range(0, len(full_output), chunk_size)]

    # Send each chunk as raw text - adapter handles formatting
    for chunk in chunks:
        await adapter_client.send_message(session_id, chunk)
        # Small delay to preserve order (platform API constraint)
        await asyncio.sleep(0.1)

    # Mark completion (MCP streaming loop will detect and stop)
    await adapter_client.send_message(session_id, "[Output Complete]")


async def poll_and_send_output(
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
) -> None:
    """Poll terminal output and send to all adapters for session.

    Pure orchestration - consumes events from poller, delegates to message manager.
    SINGLE RESPONSIBILITY: Owns the polling lifecycle for a session.

    Args:
        session_id: Session ID
        tmux_session_name: tmux session name
        output_poller: Output poller instance
        adapter_client: AdapterClient instance (broadcasts to all adapters)
        get_output_file: Function to get output file path for session
    """
    # GUARD: Prevent duplicate polling (check and add atomically before any await)
    if await db.is_polling(session_id):
        logger.warning(
            "Polling already active for session %s, ignoring duplicate request",
            session_id[:8],
        )
        return

    # Mark as active BEFORE any await (prevents race conditions)
    await db.mark_polling(session_id)

    # Get session to check type via metadata
    session = await db.get_session(session_id)

    # Update ux_state to persist polling status in DB
    await db.update_ux_state(session_id, polling_active=True)
    is_ai_session = _is_ai_to_ai_session(session)

    # Get output file and exit marker status
    output_file = get_output_file(session_id)
    # Exit marker is ALWAYS appended when starting new polling
    # (we only start polling for NEW commands, not input to running process)
    has_exit_marker = True

    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file, has_exit_marker):
            if isinstance(event, OutputChanged):
                if is_ai_session:
                    # AI mode: Send sequential chunks (no editing, no loss)
                    await _send_output_chunks_ai_mode(
                        event.session_id,
                        adapter_client,
                        event.output,
                    )
                else:
                    # Human mode: Edit same message via AdapterClient
                    await adapter_client.send_output_update(
                        event.session_id,
                        event.output,
                        event.started_at,
                        event.last_changed_at,
                    )

                # Delete idle notification if one exists (output resumed)
                ux_state = await db.get_ux_state(event.session_id)
                notification_id = ux_state.idle_notification_message_id
                if notification_id:
                    await adapter_client.delete_message(event.session_id, notification_id)
                    await db.update_ux_state(event.session_id, idle_notification_message_id=None)
                    logger.debug("Deleted idle notification %s for session %s", notification_id, event.session_id[:8])

            elif isinstance(event, IdleDetected):
                # Idle detected - send notification (broadcasts to all adapters)
                notification = (
                    f"⏸️ No output for {event.idle_seconds} seconds - " "process may be waiting or hung up, try cancel"
                )
                notification_id = await adapter_client.send_message(event.session_id, notification)
                if notification_id:
                    # Persist to DB (survives daemon restart)
                    await db.update_ux_state(event.session_id, idle_notification_message_id=notification_id)
                    logger.debug("Stored idle notification %s for session %s", notification_id, event.session_id[:8])

            elif isinstance(event, ProcessExited):
                # Process exited
                if is_ai_session:
                    # AI mode: Send final chunks + completion marker
                    await _send_output_chunks_ai_mode(
                        event.session_id,
                        adapter_client,
                        event.final_output,
                    )
                    logger.info(
                        "AI session polling stopped for %s (exit code: %s)",
                        event.session_id[:8],
                        event.exit_code,
                    )
                else:
                    # Human mode: Send final message
                    if event.exit_code is not None:
                        # Exit with code - send final message via AdapterClient
                        await adapter_client.send_output_update(
                            event.session_id,
                            event.final_output,
                            event.started_at,  # Use actual start time from poller
                            time.time(),
                            is_final=True,
                            exit_code=event.exit_code,
                        )
                        logger.info(
                            "Polling stopped for %s (exit code: %d), output file kept for downloads",
                            event.session_id[:8],
                            event.exit_code,
                        )
                    else:
                        # Session died - send exit message via AdapterClient
                        await adapter_client.send_exit_message(
                            event.session_id,
                            event.final_output,
                            "✅ Process exited",
                        )
                        # Delete output file on session death
                        try:
                            if output_file.exists():
                                output_file.unlink()
                                logger.debug("Deleted output file for exited session %s", event.session_id[:8])
                        except Exception as e:
                            logger.warning("Failed to delete output file: %s", e)

    finally:
        # Cleanup state
        await db.unmark_polling(session_id)
        await db.clear_pending_deletions(session_id)
        # NOTE: Keep output_message_id in DB - it's reused for all commands in the session
        # Only cleared when session closes (/exit command)

        # Clear idle notification
        await db.update_ux_state(session_id, idle_notification_message_id=None)

        logger.debug("Polling ended for session %s", session_id[:8])
