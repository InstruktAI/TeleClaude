"""Polling coordinator for terminal output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)

_ANSI_ESCAPE_RE = re.compile("\x1b\\[[0-?]*[ -/]*[@-~]")
_EXIT_MARKER_RE = re.compile(r"__EXIT__\d+__\n?")


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


async def poll_and_send_output(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
    marker_id: Optional[str] = None,
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
        marker_id: Unique marker ID for exit detection (None = no exit marker)
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

    # Update ux_state to persist polling status in DB
    await db.update_ux_state(session_id, polling_active=True)

    # Get output file
    output_file = get_output_file(session_id)

    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file, marker_id):
            if isinstance(event, OutputChanged):
                logger.debug(
                    "[COORDINATOR %s] Received OutputChanged event from poller",
                    session_id[:8],
                )
                # Output is already clean (poller writes filtered output to file)
                clean_output = event.output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)

                # Unified output handling - ALL sessions use send_output_update
                start_time = time.time()
                logger.debug("[COORDINATOR %s] Calling send_output_update...", session_id[:8])
                await adapter_client.send_output_update(
                    session,  # type: ignore[arg-type]
                    clean_output,
                    event.started_at,
                    event.last_changed_at,
                )
                elapsed = time.time() - start_time
                logger.debug(
                    "[COORDINATOR %s] send_output_update completed in %.2fs",
                    session_id[:8],
                    elapsed,
                )

            elif isinstance(event, DirectoryChanged):
                # Directory changed - update session (db dispatcher handles title update)
                await db.update_session(event.session_id, working_directory=event.new_path)

            elif isinstance(event, ProcessExited):
                # Process exited - output is already clean from file
                clean_final_output = event.final_output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)

                # Unified output handling - ALL sessions use send_output_update
                if event.exit_code is not None:
                    # Exit with code - send final message via AdapterClient
                    await adapter_client.send_output_update(
                        session,  # type: ignore[arg-type]
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
                    if session and session.closed:
                        # Session was intentionally closed by user - don't send exit message
                        logger.debug(
                            "Session %s was closed by user, skipping exit message",
                            event.session_id[:8],
                        )
                    elif session:
                        # Tmux session died unexpectedly - notify user
                        try:
                            await adapter_client.send_exit_message(
                                session,
                                event.final_output,
                                "⚠️ Session terminated abnormally",
                            )
                        except Exception as e:
                            # Handle errors gracefully (e.g., message too long, topic closed)
                            logger.warning(
                                "Failed to send exit message for %s: %s",
                                event.session_id[:8],
                                e,
                            )

                    # Delete output file on session death
                    try:
                        if output_file.exists():
                            output_file.unlink()
                            logger.debug(
                                "Deleted output file for exited session %s",
                                event.session_id[:8],
                            )
                    except Exception as e:
                        logger.warning("Failed to delete output file: %s", e)

    finally:
        # Cleanup state
        await db.unmark_polling(session_id)
        # NOTE: Don't clear pending_deletions here - let _pre_handle_user_input handle deletion on next input
        # NOTE: Keep output_message_id in DB - it's reused for all commands in the session
        # Only cleared when session closes (/exit command)

        logger.debug("Polling ended for session %s", session_id[:8])
