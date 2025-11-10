"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    format_terminal_message,
)

logger = logging.getLogger(__name__)


class UiAdapter(BaseAdapter):
    """Base class for UI-enabled adapters.

    Provides default output message management for platforms with editable messages.
    Subclasses can override for platform-specific UX (e.g., Telegram: edit first 10s).
    """

    has_ui: bool = True

    # === Command Registration ===

    # Standard UI commands - subclasses implement handlers with _handle_{command} naming
    COMMANDS = [
        "new_session",
        "list_sessions",
        "list_projects",
        "cancel",
        "cancel2x",
        "kill",
        "escape",
        "escape2x",
        "ctrl",
        "tab",
        "shift_tab",
        "key_up",
        "key_down",
        "key_left",
        "key_right",
        "resize",
        "rename",
        "cd",
        "claude",
        "claude_resume",
        "help",
    ]

    def _get_command_handlers(self) -> list[tuple[str, object]]:
        """Get command handlers by convention: command_name → _handle_{command_name}.

        Returns:
            List of (command_name, handler_method) tuples
        """
        handlers = []
        for command in self.COMMANDS:
            handler_name = f"_handle_{command}"
            handler = getattr(self, handler_name, None)
            if handler:
                handlers.append((command, handler))
            else:
                logger.warning("Handler %s not found for command %s", handler_name, command)
        return handlers

    # === Output Message Management (Default Implementations) ===

    async def send_output_update(
        self,
        session_id: str,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: Optional[int] = None,
    ) -> Optional[str]:
        """Send or edit output message - default: always edit existing message.

        Subclasses can override for platform-specific UX.
        """
        ux_state = await db.get_ux_state(session_id)
        current_message_id = ux_state.output_message_id

        # Truncate if needed (4096 Telegram limit - 196 chars overhead = 3900 max terminal output)
        max_terminal_output = 3900
        is_truncated = len(output) > max_terminal_output
        terminal_output = output[-max_terminal_output:] if is_truncated else output

        # Format status line
        if is_final and exit_code is not None:
            size_str = format_size(len(output.encode("utf-8")))
            status_line = format_completed_status_line(exit_code, started_at, size_str, is_truncated)
        else:
            # Active status
            tz = ZoneInfo(config.computer.timezone)
            started_time = datetime.fromtimestamp(started_at, tz=tz).strftime("%H:%M:%S")
            current_time = time.time()
            last_active_time = datetime.fromtimestamp(current_time, tz=tz).strftime("%H:%M:%S")

            # Status color based on idle time
            idle_seconds = int(time.time() - last_output_changed_at)
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
        metadata: dict[str, object] = {}
        if is_truncated:
            keyboard = [[InlineKeyboardButton("📎 Download full output", callback_data=f"download_full:{session_id}")]]
            metadata["reply_markup"] = InlineKeyboardMarkup(keyboard)

        # Send or edit
        if current_message_id:
            success = await self.edit_message(
                session_id, current_message_id, display_output, metadata if metadata else None
            )
            if success:
                return current_message_id
            # Edit failed - clear stale message_id and send new
            logger.warning("Failed to edit message %s, clearing stale message_id and sending new", current_message_id)
            await db.update_ux_state(session_id, output_message_id=None)

        new_id = await self.send_message(session_id, display_output, metadata if metadata else None)
        if new_id:
            await db.update_ux_state(session_id, output_message_id=new_id)
            logger.debug("Stored message_id=%s for session=%s", new_id, session_id[:8])
        return new_id

    async def send_status_message(
        self,
        session_id: str,
        text: str,
        append_to_existing: bool = False,
        output_file_path: Optional[str] = None,
    ) -> Optional[str]:
        """Send immediate status message - default implementation."""
        if append_to_existing:
            # Append to existing output message
            ux_state = await db.get_ux_state(session_id)
            current_message_id = ux_state.output_message_id
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
            current_output = output_file.read_text(encoding="utf-8") if output_file.exists() else ""

            # Format: terminal output in code block, status OUTSIDE the block
            display_output = format_terminal_message(current_output, text)

            # Edit existing message with status appended
            success = await self.edit_message(session_id, current_message_id, display_output)

            if not success:
                # Edit failed - clear stale message_id and send new
                logger.warning(
                    "Failed to edit message %s, clearing stale message_id and sending new", current_message_id
                )
                await db.update_ux_state(session_id, output_message_id=None)
            else:
                logger.debug("Appended status '%s' to existing message for session %s", text, session_id[:8])
                return current_message_id

        # Send new ephemeral message
        logger.debug("send_status_message: session=%s, append=False, sending new message: %s", session_id[:8], text)
        message_id = await self.send_message(session_id, text)
        return message_id

    async def send_exit_message(self, session_id: str, output: str, exit_text: str) -> None:
        """Send exit message when session dies - default implementation."""
        ux_state = await db.get_ux_state(session_id)
        current_message_id = ux_state.output_message_id
        final_output = format_terminal_message(output if output else "", exit_text)
        metadata: dict[str, object] = {"raw_format": True}

        if current_message_id:
            success = await self.edit_message(session_id, current_message_id, final_output)
            if not success:
                # Edit failed - clear stale message_id and send new message
                logger.warning(
                    "Failed to edit message %s, clearing stale message_id and sending new", current_message_id
                )
                await db.update_ux_state(session_id, output_message_id=None)
                new_id = await self.send_message(session_id, final_output, metadata)
                if new_id:
                    await db.update_ux_state(session_id, output_message_id=new_id)
        else:
            new_id = await self.send_message(session_id, final_output, metadata)
            if new_id:
                await db.update_ux_state(session_id, output_message_id=new_id)

    async def cleanup_feedback_messages(self, session_id: str) -> None:
        """Delete temporary feedback messages - default implementation."""
        ux_state = await db.get_ux_state(session_id)
        pending_deletions = ux_state.pending_deletions or []

        if not pending_deletions:
            return

        for message_id in pending_deletions:
            try:
                await self.delete_message(session_id, message_id)
                logger.debug("Deleted feedback message %s for session %s", message_id, session_id[:8])
            except Exception as e:
                logger.warning("Failed to delete message %s: %s", message_id, e)

        # Clear pending deletions
        await db.update_ux_state(session_id, pending_deletions=[])

    # ==================== Voice Support ====================

    async def _process_voice_input(
        self,
        session_id: str,
        audio_file_path: str,
        context: dict[str, object],
    ) -> None:
        """Shared voice processing logic for UI adapters.

        Default implementation uses voice_message_handler.py utility.
        Override if platform needs custom voice handling.

        Flow:
        1. Validate session and check if process is running
        2. Send "Transcribing..." feedback to user
        3. Transcribe audio using voice_message_handler.py
        4. Send transcribed text to terminal
        5. Send feedback on success/failure

        Args:
            session_id: Session ID
            audio_file_path: Path to audio file (any format supported by Whisper)
            context: Platform-specific metadata (user_id, duration, etc.)
        """
        from teleclaude.core.voice_message_handler import handle_voice

        # Delegate to utility module
        await handle_voice(
            session_id=session_id,
            audio_path=audio_file_path,
            context=context,
            send_feedback=lambda sid, msg, append: self.send_message(sid, msg),
            get_output_file=self._get_output_file_path,
        )

    # ==================== File Handling ====================

    async def get_session_file(
        self,
        session_id: str,
    ) -> Optional[str]:
        """Provide platform-specific download UI for session output.

        OPTIONAL - Override if platform supports download functionality.

        Examples:
        - TelegramAdapter: Upload file to Telegram, create download button, return message_id
        - WhatsAppAdapter: Upload to WhatsApp as media message

        Args:
            session_id: Session identifier

        Returns:
            Platform-specific identifier/link if download UI created, None otherwise

        NOTE: This is different from _get_output_file_path() which returns local file PATH.
        """
        return None  # Default: no download functionality

    def _get_output_file_path(self, session_id: str) -> Path:
        """Get local file system PATH to session output file.

        Used internally by UI adapters that need to READ the output file
        (e.g., for uploading, processing, voice status appending).

        Default implementation uses standard session_output directory.
        Override if adapter stores output files in custom location.

        Args:
            session_id: Session identifier

        Returns:
            Path object pointing to local file (e.g., "session_output/abc123.txt")

        NOTE: This is different from get_session_file() which creates download UI.
        """
        # Use standard session_output directory (same as daemon)
        return Path("session_output") / f"{session_id[:8]}.txt"
