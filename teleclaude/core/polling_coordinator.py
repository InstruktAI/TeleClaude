"""Polling coordinator for terminal output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.output_poller import (
    DirectoryChanged,
    IdleDetected,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.utils import strip_ansi_codes, strip_exit_markers

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


def _filter_for_ui(raw_output: str) -> str:
    """Filter raw terminal output for UI display.

    Strips ANSI escape codes, exit markers, and collapses excessive blank lines.

    Args:
        raw_output: Raw terminal output with ANSI codes and markers

    Returns:
        Filtered output ready for UI display
    """
    filtered = strip_ansi_codes(raw_output)
    filtered = strip_exit_markers(filtered)

    # Collapse multiple consecutive newlines into single newline
    # This reduces excessive blank lines while preserving line structure
    filtered = re.sub(r"\n\n+", "\n", filtered)

    return filtered


async def restore_active_pollers(
    adapter_client: "AdapterClient",
    output_poller: OutputPoller,
    get_output_file: Callable[[str], Path],
) -> None:
    """Restore polling for sessions that were active before daemon restart.

    Called during daemon startup to resume polling for sessions with polling_active=True.
    Prevents the "frozen session" bug where database says polling is active but no poller is running.

    Args:
        adapter_client: AdapterClient instance for message sending
        output_poller: Output poller instance
        get_output_file: Function to get output file path for session
    """
    from teleclaude.core import terminal_bridge

    # Query sessions with polling_active=True
    sessions = await db.get_active_sessions()
    if not sessions:
        logger.info("No active polling sessions to restore")
        return

    logger.info("Restoring polling for %d sessions...", len(sessions))

    for session in sessions:
        session_id = session.session_id
        tmux_session_name = session.tmux_session_name

        # Check if tmux session still exists
        if not await terminal_bridge.session_exists(tmux_session_name):
            logger.warning(
                "Tmux session %s for session %s no longer exists, marking polling as inactive",
                tmux_session_name,
                session_id[:8],
            )
            await db.set_polling_inactive(session_id)
            continue

        # Reset polling flag before restarting (allows guard to pass)
        logger.info("Restoring polling for session %s (%s)", session_id[:8], tmux_session_name)
        await db.set_polling_inactive(session_id)

        # Use create_task to avoid blocking startup
        asyncio.create_task(
            poll_and_send_output(
                session_id=session_id,
                tmux_session_name=tmux_session_name,
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
            )
        )

    logger.info("Session restoration complete")


def _is_ai_to_ai_session(session: Session) -> bool:
    """Check if session is AI-to-AI by presence of target_computer.

    Args:
        session: Session object with adapter_metadata

    Returns:
        True if AI-to-AI session (has target_computer), False otherwise (Human-to-AI)
    """
    if not session or not session.adapter_metadata:
        return False
    # AI-to-AI sessions have target_computer in metadata
    return bool(session.adapter_metadata.get("target_computer"))


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
    # Conservative chunk size (avoid Telegram message splitting)
    chunk_size = 3750

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
    has_exit_marker: bool = True,
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
        has_exit_marker: Whether exit marker was appended (default: True)
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

    # Get output file
    output_file = get_output_file(session_id)

    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file, has_exit_marker):
            if isinstance(event, OutputChanged):
                # Output is already clean (poller writes filtered output to file)
                clean_output = event.output

                if is_ai_session:
                    # AI mode: Send sequential chunks (no editing, no loss)
                    await _send_output_chunks_ai_mode(
                        event.session_id,
                        adapter_client,
                        clean_output,
                    )
                else:
                    # Human mode: Edit same message via AdapterClient
                    await adapter_client.send_output_update(
                        event.session_id,
                        clean_output,
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

                # Clear notification_sent flag (activity detected, re-enable notifications)
                if ux_state.notification_sent:
                    await db.clear_notification_flag(event.session_id)
                    logger.debug(
                        "Cleared notification_sent flag for session %s (activity detected)", event.session_id[:8]
                    )

            elif isinstance(event, IdleDetected):
                # Check if Claude Code notification was sent (skip idle notification if so)
                notification_sent = await db.get_notification_flag(event.session_id)
                if notification_sent:
                    logger.debug(
                        "Skipping idle notification for session %s (Claude Code notification sent)",
                        event.session_id[:8],
                    )
                    continue

                # Idle detected - send notification (broadcasts to all adapters)
                notification = (
                    f"⏸️ No output for {event.idle_seconds} seconds - " "process may be waiting or hung up, try cancel"
                )
                notification_id = await adapter_client.send_message(event.session_id, notification)
                if notification_id:
                    # Persist to DB (survives daemon restart)
                    await db.update_ux_state(event.session_id, idle_notification_message_id=notification_id)
                    logger.debug("Stored idle notification %s for session %s", notification_id, event.session_id[:8])

            elif isinstance(event, DirectoryChanged):
                # Directory changed - update session (db dispatcher handles title update)
                await db.update_session(event.session_id, working_directory=event.new_path)

            elif isinstance(event, ProcessExited):
                # Process exited - output is already clean from file
                clean_final_output = event.final_output

                if is_ai_session:
                    # AI mode: Send final chunks + completion marker
                    await _send_output_chunks_ai_mode(
                        event.session_id,
                        adapter_client,
                        clean_final_output,
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
                            clean_final_output,
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
                        # Session died - check if it was user-closed before sending exit message
                        session = await db.get_session(event.session_id)
                        if session and session.closed:
                            # Session was intentionally closed by user - don't send exit message
                            logger.debug("Session %s was closed by user, skipping exit message", event.session_id[:8])
                        else:
                            # Unexpected death - send exit message via AdapterClient
                            try:
                                await adapter_client.send_exit_message(
                                    event.session_id,
                                    event.final_output,
                                    "✅ Process exited",
                                )
                            except Exception as e:
                                # Handle errors gracefully (e.g., message too long, topic closed)
                                logger.warning("Failed to send exit message for %s: %s", event.session_id[:8], e)

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
