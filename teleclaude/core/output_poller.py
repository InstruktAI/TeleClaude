"""Terminal output polling - simple and explicit.

Polls terminal output and sends updates to chat adapter until process completes.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    format_terminal_message,
)

logger = logging.getLogger(__name__)


class OutputPoller:
    """Polls terminal output and sends updates to chat adapter."""

    def __init__(self, config: dict[str, Any], terminal: TerminalBridge, session_manager: SessionManager):
        """Initialize poller.

        Args:
            config: Application config
            terminal: Terminal bridge for tmux operations
            session_manager: Session manager (currently unused)
        """
        self.config = config
        self.terminal = terminal
        self.session_manager = session_manager

    async def poll_and_send_output(
        self,
        session_id: str,
        tmux_session_name: str,
        adapter: BaseAdapter,
        output_dir: Path,
        active_polling_sessions: set[str],
        long_running_sessions: set[str],
        idle_notifications: dict[str, str],
        exit_marker_appended: dict[str, bool],
    ) -> None:
        """Poll terminal output until process completes.

        EXPLICIT control flow - read top-to-bottom to understand what happens.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            adapter: Adapter for sending messages
            output_dir: Directory for output files
            active_polling_sessions: Set to track active sessions
            long_running_sessions: Set to track long-running sessions (unused)
            idle_notifications: Dict to track idle notification messages
            exit_marker_appended: Dict to track exit marker status
        """
        # Configuration
        idle_threshold = self.config.get("polling", {}).get("idle_notification_seconds", 60)
        max_message_length = 3800
        poll_interval = 1.0

        # State tracking (simple variables)
        has_exit_marker = exit_marker_appended.get(session_id, False)
        output_file = output_dir / f"{session_id[:8]}.txt"
        message_id = None
        output_buffer = ""
        idle_ticks = 0
        notification_sent = False
        started_at = None
        last_output_changed_at = None
        last_message_updated_at = None

        # Mark session as active
        active_polling_sessions.add(session_id)

        try:
            # Initial delay
            await asyncio.sleep(1.0)
            started_at = asyncio.get_event_loop().time()
            last_output_changed_at = started_at

            # Poll loop - EXPLICIT EXIT CONDITIONS
            while True:
                # Exit condition 1: Session died
                if not await self.terminal.session_exists(tmux_session_name):
                    logger.info("Process exited for %s, stopping poll", session_id[:8])
                    await self._send_exit_message(adapter, session_id, output_buffer, message_id, "✅ Process exited")
                    # Delete output file on session death
                    try:
                        if output_file.exists():
                            output_file.unlink()
                            logger.debug("Deleted output file for exited session %s", session_id[:8])
                    except Exception as e:
                        logger.warning("Failed to delete output file: %s", e)
                    break

                # Capture current output
                current_output = await self.terminal.capture_pane(tmux_session_name)
                if not current_output.strip():
                    # No output yet, keep polling
                    await asyncio.sleep(poll_interval)
                    continue

                # Exit condition 2: Exit code detected
                exit_code = self._extract_exit_code(current_output, has_exit_marker)
                if exit_code is not None:
                    # Strip marker from output
                    current_output = re.sub(r"\n?__EXIT__\d+__\n?", "", current_output)
                    logger.info("Exit code %d detected for %s", exit_code, session_id[:8])

                    # Write final output to file for downloads
                    try:
                        output_file.write_text(current_output, encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to write final output file: %s", e)

                    # Send final message
                    await self._send_final_message(
                        adapter,
                        session_id,
                        current_output,
                        message_id,
                        exit_code,
                        started_at,
                        max_message_length,
                    )
                    # Keep output file for downloads
                    break

                # Check if output changed
                if current_output != output_buffer:
                    # Output changed - reset idle counter
                    output_buffer = current_output
                    idle_ticks = 0
                    notification_sent = False
                    last_output_changed_at = asyncio.get_event_loop().time()

                    # Write to file
                    try:
                        output_file.write_text(output_buffer, encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to write output file: %s", e)

                    # Update message
                    message_id = await self._update_message(
                        adapter,
                        session_id,
                        output_buffer,
                        message_id,
                        started_at,
                        last_output_changed_at,
                        max_message_length,
                    )
                    last_message_updated_at = asyncio.get_event_loop().time()

                else:
                    # Output unchanged - increment idle counter
                    idle_ticks += 1

                    # Send idle notification once at threshold
                    if idle_ticks == idle_threshold and not notification_sent:
                        await self._send_idle_notification(adapter, session_id, idle_threshold, idle_notifications)
                        notification_sent = True

                    # Update timer every 5 seconds
                    elif not notification_sent:
                        now = asyncio.get_event_loop().time()
                        time_since_update = (now - last_message_updated_at) if last_message_updated_at else 999
                        if time_since_update >= 5.0:
                            message_id = await self._update_message(
                                adapter,
                                session_id,
                                output_buffer,
                                message_id,
                                started_at,
                                last_output_changed_at,
                                max_message_length,
                            )
                            last_message_updated_at = now

                await asyncio.sleep(poll_interval)

        finally:
            # Cleanup
            active_polling_sessions.discard(session_id)
            exit_marker_appended.pop(session_id, None)
            idle_notifications.pop(session_id, None)
            logger.debug("Polling ended for session %s", session_id[:8])

    # =========================================================================
    # Pure utilities (no side effects)
    # =========================================================================

    def _extract_exit_code(self, output: str, has_exit_marker: bool) -> Optional[int]:
        """Extract exit code from output if marker present.

        Args:
            output: Terminal output
            has_exit_marker: Whether exit marker was appended

        Returns:
            Exit code or None
        """
        if not has_exit_marker:
            return None
        match = re.search(r"__EXIT__(\d+)__", output)
        return int(match.group(1)) if match else None

    # =========================================================================
    # I/O operations (explicit side effects)
    # =========================================================================

    async def _update_message(
        self,
        adapter: BaseAdapter,
        session_id: str,
        output: str,
        message_id: Optional[str],
        started_at: float,
        last_output_changed_at: float,
        max_message_length: int,
    ) -> str:
        """Send or update output message.

        Args:
            adapter: Adapter for sending messages
            session_id: Session ID
            output: Terminal output
            message_id: Current message ID (None if not sent yet)
            started_at: When process started
            last_output_changed_at: When output last changed
            max_message_length: Max message length for truncation

        Returns:
            Message ID
        """
        # Truncate if needed
        is_truncated = len(output) > max_message_length
        terminal_output = output[-(max_message_length - 400) :] if is_truncated else output

        # Format timestamps
        tz_name = self.config.get("computer", {}).get("timezone", "Europe/Amsterdam")
        tz = ZoneInfo(tz_name)
        started_time = datetime.fromtimestamp(started_at, tz=tz).strftime("%H:%M:%S")
        last_active_time = datetime.fromtimestamp(last_output_changed_at, tz=tz).strftime("%H:%M:%S")

        # Status color based on idle time
        idle_seconds = int(asyncio.get_event_loop().time() - last_output_changed_at)
        if idle_seconds <= 5:
            status_color = "⚪"
        elif idle_seconds <= 10:
            status_color = "🟡"
        elif idle_seconds <= 20:
            status_color = "🟠"
        else:
            status_color = "🔴"

        # Size
        size_str = format_size(len(output.encode("utf-8")))

        # Build message
        status_line = format_active_status_line(status_color, started_time, last_active_time, size_str, is_truncated)
        display_output = format_terminal_message(terminal_output, status_line)

        # Metadata
        metadata = {"raw_format": True}
        if is_truncated:
            keyboard = [[InlineKeyboardButton("📎 Download full output", callback_data=f"download_full:{session_id}")]]
            metadata["reply_markup"] = InlineKeyboardMarkup(keyboard)

        # Send or edit
        if message_id:
            await adapter.edit_message(session_id, message_id, display_output, metadata)
            return message_id
        else:
            new_id = await adapter.send_message(session_id, display_output, metadata)
            return new_id if new_id else message_id

    async def _send_idle_notification(
        self,
        adapter: BaseAdapter,
        session_id: str,
        idle_threshold: int,
        idle_notifications: dict[str, str],
    ) -> None:
        """Send idle notification.

        Args:
            adapter: Adapter for sending messages
            session_id: Session ID
            idle_threshold: Idle threshold in seconds
            idle_notifications: Dict to track idle notifications
        """
        logger.info("No output change for %ds for %s, notifying user", idle_threshold, session_id[:8])
        notification = f"⏸️ No output for {idle_threshold} seconds - process may be waiting or hung up, try cancel"
        notification_id = await adapter.send_message(session_id, notification)

        if notification_id:
            idle_notifications[session_id] = notification_id
            logger.debug("Stored idle notification %s for session %s", notification_id, session_id[:8])

    async def _send_exit_message(
        self,
        adapter: BaseAdapter,
        session_id: str,
        output: str,
        message_id: Optional[str],
        exit_text: str,
    ) -> None:
        """Send exit message.

        Args:
            adapter: Adapter for sending messages
            session_id: Session ID
            output: Terminal output
            message_id: Current message ID
            exit_text: Exit message text
        """
        final_output = format_terminal_message(output if output else "", exit_text)
        metadata = {"raw_format": True}

        if message_id:
            await adapter.edit_message(session_id, message_id, final_output, metadata)
        else:
            await adapter.send_message(session_id, final_output, metadata)

    async def _send_final_message(
        self,
        adapter: BaseAdapter,
        session_id: str,
        output: str,
        message_id: Optional[str],
        exit_code: int,
        started_at: float,
        max_message_length: int,
    ) -> None:
        """Send final message with exit code.

        Args:
            adapter: Adapter for sending messages
            session_id: Session ID
            output: Terminal output
            message_id: Current message ID
            exit_code: Exit code
            started_at: When process started
            max_message_length: Max message length for truncation
        """
        # Truncate if needed
        is_truncated = len(output) > max_message_length
        terminal_output = output[-(max_message_length - 400) :] if is_truncated else output

        # Format final message
        size_str = format_size(len(output.encode("utf-8")))
        status_line = format_completed_status_line(exit_code, started_at, size_str, is_truncated)
        final_output = format_terminal_message(terminal_output if output else "", status_line)

        # Metadata with download button if truncated
        final_metadata = {"raw_format": True}
        if is_truncated:
            keyboard = [[InlineKeyboardButton("📎 Download full output", callback_data=f"download_full:{session_id}")]]
            final_metadata["reply_markup"] = InlineKeyboardMarkup(keyboard)

        # Send/edit
        if message_id:
            await adapter.edit_message(session_id, message_id, final_output, final_metadata)
        else:
            await adapter.send_message(session_id, final_output, final_metadata)

        logger.info("Polling stopped for %s (exit code: %d), output file kept for downloads", session_id[:8], exit_code)
