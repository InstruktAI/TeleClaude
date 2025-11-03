"""Centralized output message management - decoupled from polling logic."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.core.session_manager import SessionManager
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    format_terminal_message,
)

logger = logging.getLogger(__name__)


class OutputMessageManager:
    """Manages output messages for sessions.

    Separates message tracking and sending from polling logic.
    Enables immediate status messages during long-running processes.
    """

    def __init__(self, config: dict[str, Any], session_manager: SessionManager):
        """Initialize message manager.

        Args:
            config: Application config
            session_manager: Session manager for persisting message IDs
        """
        self.config = config
        self.session_manager = session_manager

    async def send_status_message(
        self,
        session_id: str,
        adapter: BaseAdapter,
        text: str,
        append_to_existing: bool = False,
        output_file_path: Optional[str] = None,
    ) -> Optional[str]:
        """Send immediate status message.

        Args:
            session_id: Session ID
            adapter: Adapter for sending messages
            text: Status text to send
            append_to_existing: If True, append to existing polling output message
            output_file_path: Path to output file (required if append_to_existing=True)

        Returns:
            Message ID of sent/edited message
        """
        if append_to_existing:
            # Append to existing output message (process is actively polling)
            current_message_id = await self.session_manager.get_output_message_id(session_id)
            logger.debug(
                "send_status_message: session=%s, append=True, message_id=%s, output_file=%s",
                session_id[:8],
                current_message_id,
                output_file_path,
            )
            if not current_message_id or not output_file_path:
                logger.warning("Cannot append status - no message ID or output file for session %s", session_id[:8])
                return None

            output_file = Path(output_file_path)
            current_output = output_file.read_text() if output_file.exists() else ""

            # Format: terminal output in code block, status OUTSIDE the block
            display_output = format_terminal_message(current_output, text)

            # Edit existing message with status appended
            success = await adapter.edit_message(
                session_id,
                current_message_id,
                display_output,
                {"raw_format": True},
            )

            if not success:
                # Edit failed (stale message_id) - clear it and send new message
                logger.warning(
                    "Failed to edit message %s, clearing stale message_id and sending new", current_message_id
                )
                await self.session_manager.set_output_message_id(session_id, None)
                # Fall through to send new message below
            else:
                logger.debug("Appended status '%s' to existing message for session %s", text, session_id[:8])
                return current_message_id

        # Send new ephemeral message
        logger.debug(
            "send_status_message: session=%s, append=False, sending new message: %s",
            session_id[:8],
            text,
        )
        message_id = await adapter.send_message(session_id, text)
        return message_id

    async def send_output_update(
        self,
        session_id: str,
        adapter: BaseAdapter,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        max_message_length: int = 3800,
        is_final: bool = False,
        exit_code: Optional[int] = None,
    ) -> Optional[str]:
        """Send or edit output message for a session.

        Args:
            session_id: Session ID
            adapter: Adapter for sending messages
            output: Terminal output
            started_at: When process started
            last_output_changed_at: When output last changed
            max_message_length: Max message length for truncation
            is_final: Whether this is the final message (process completed)
            exit_code: Exit code if process completed

        Returns:
            Message ID
        """
        current_message_id = await self.session_manager.get_output_message_id(session_id)

        # Truncate if needed
        is_truncated = len(output) > max_message_length
        terminal_output = output[-(max_message_length - 400) :] if is_truncated else output

        # Format status line
        if is_final and exit_code is not None:
            size_str = format_size(len(output.encode("utf-8")))
            status_line = format_completed_status_line(exit_code, started_at, size_str, is_truncated)
        else:
            # Active status
            tz_name = self.config.get("computer", {}).get("timezone", "Europe/Amsterdam")
            tz = ZoneInfo(tz_name)
            started_time = datetime.fromtimestamp(started_at, tz=tz).strftime("%H:%M:%S")
            # "last active" shows CURRENT time (when message is sent/edited)
            current_time = asyncio.get_event_loop().time()
            last_active_time = datetime.fromtimestamp(current_time, tz=tz).strftime("%H:%M:%S")

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

            size_str = format_size(len(output.encode("utf-8")))
            status_line = format_active_status_line(
                status_color, started_time, last_active_time, size_str, is_truncated
            )

        # Build message
        display_output = format_terminal_message(terminal_output, status_line)

        # Metadata with download button if truncated
        metadata = {"raw_format": True}
        if is_truncated:
            keyboard = [[InlineKeyboardButton("📎 Download full output", callback_data=f"download_full:{session_id}")]]
            metadata["reply_markup"] = InlineKeyboardMarkup(keyboard)

        # Send or edit
        if current_message_id:
            success = await adapter.edit_message(session_id, current_message_id, display_output, metadata)
            if success:
                return current_message_id
            # Edit failed - clear stale message_id and send new
            logger.warning("Failed to edit message %s, clearing stale message_id and sending new", current_message_id)
            await self.session_manager.set_output_message_id(session_id, None)

        new_id = await adapter.send_message(session_id, display_output, metadata)
        if new_id:
            await self.session_manager.set_output_message_id(session_id, new_id)
            logger.debug("Stored message_id=%s for session=%s", new_id, session_id[:8])
        return new_id

    async def send_exit_message(
        self,
        session_id: str,
        adapter: BaseAdapter,
        output: str,
        exit_text: str,
    ) -> None:
        """Send exit message when session dies.

        Args:
            session_id: Session ID
            adapter: Adapter for sending messages
            output: Terminal output
            exit_text: Exit message text
        """
        current_message_id = await self.session_manager.get_output_message_id(session_id)
        final_output = format_terminal_message(output if output else "", exit_text)
        metadata = {"raw_format": True}

        if current_message_id:
            success = await adapter.edit_message(session_id, current_message_id, final_output, metadata)
            if not success:
                # Edit failed - send new message
                await adapter.send_message(session_id, final_output, metadata)
        else:
            await adapter.send_message(session_id, final_output, metadata)

        # Remove from tracking
        await self.session_manager.set_output_message_id(session_id, None)

    async def get_current_message_id(self, session_id: str) -> Optional[str]:
        """Get current output message ID for a session.

        Args:
            session_id: Session ID

        Returns:
            Message ID or None
        """
        return await self.session_manager.get_output_message_id(session_id)

    async def clear_session(self, session_id: str) -> None:
        """Clear message tracking for a session.

        Args:
            session_id: Session ID
        """
        await self.session_manager.set_output_message_id(session_id, None)
