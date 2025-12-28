"""Polling coordinator for terminal output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_active_pollers: set[str] = set()
_poller_lock = asyncio.Lock()


async def is_polling(session_id: str) -> bool:
    """Check if a poller task is active for the session (in-memory only)."""
    async with _poller_lock:
        return session_id in _active_pollers


async def _register_polling(session_id: str) -> bool:
    """Register a poller task if one isn't active. Returns True if registered."""
    async with _poller_lock:
        if session_id in _active_pollers:
            return False
        _active_pollers.add(session_id)
        return True


async def _unregister_polling(session_id: str) -> None:
    """Unregister a poller task."""
    async with _poller_lock:
        _active_pollers.discard(session_id)


async def schedule_polling(
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
) -> bool:
    """Schedule polling in the background with an in-memory guard.

    Returns True if scheduled, False if a poller is already active.
    """
    if not await _register_polling(session_id):
        logger.warning(
            "Polling already active for session %s, ignoring duplicate request",
            session_id[:8],
        )
        return False

    asyncio.create_task(
        poll_and_send_output(
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            output_poller=output_poller,
            adapter_client=adapter_client,
            get_output_file=get_output_file,
            _skip_register=True,
        )
    )
    return True


async def poll_and_send_output(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
    _skip_register: bool = False,
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
    if not _skip_register:
        if not await _register_polling(session_id):
            logger.warning(
                "Polling already active for session %s, ignoring duplicate request",
                session_id[:8],
            )
            return

    # Get output file
    output_file = get_output_file(session_id)

    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file):
            if isinstance(event, OutputChanged):
                logger.trace(
                    "[COORDINATOR %s] Received OutputChanged event from poller",
                    session_id[:8],
                )
                # Output is already clean (poller writes filtered output to file)
                clean_output = event.output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)

                # Unified output handling - ALL sessions use send_output_update
                start_time = time.time()
                logger.trace("[COORDINATOR %s] Calling send_output_update...", session_id[:8])
                await adapter_client.send_output_update(
                    session,  # type: ignore[arg-type]
                    clean_output,
                    event.started_at,
                    event.last_changed_at,
                )
                elapsed = time.time() - start_time
                logger.trace(
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
        await _unregister_polling(session_id)
        # NOTE: Don't clear pending_deletions here - let _pre_handle_user_input handle deletion on next input
        # NOTE: Keep output_message_id in DB - it's reused for all commands in the session
        # Only cleared when session closes (/exit command)

        logger.debug("Polling ended for session %s", session_id[:8])
