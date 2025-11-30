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

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.voice_message_handler import handle_voice
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    format_terminal_message,
    strip_ansi_codes,
    strip_exit_markers,
)

logger = logging.getLogger(__name__)


class UiAdapter(BaseAdapter):
    """Base class for UI-enabled adapters.

    Provides output message management for platforms with editable messages.
    Subclasses can override max_message_size and add platform-specific formatting.
    """

    # Platform message size limit (subclasses can override)
    # Default: 3900 chars (Telegram: 4096 limit - ~196 overhead)
    max_message_size: int = 3900

    def _get_adapter_key(self) -> str:
        """Get adapter key for metadata storage.

        Uses class name to determine adapter type at runtime.

        Returns:
            Adapter key string (e.g., "telegram", "redis")
        """
        class_name = self.__class__.__name__
        if class_name == "TelegramAdapter":
            return "telegram"
        if class_name == "RedisAdapter":
            return "redis"
        return "unknown"

    # === Command Registration ===

    # Standard UI commands - subclasses implement handlers with _handle_{command} naming
    COMMANDS = [
        "new_session",
        "list_sessions",
        "list_projects",
        "get_session_data",  # Get session data from claude_session_file (inherited from BaseAdapter)
        "cancel",
        "cancel2x",
        "kill",
        "escape",
        "escape2x",
        "ctrl",
        "tab",
        "shift_tab",
        "backspace",
        "claude_plan",
        "enter",
        "key_up",
        "key_down",
        "key_left",
        "key_right",
        "resize",
        "rename",
        "cd",
        "claude",
        "claude_resume",
        "claude_restart",
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
        """Send or edit output message - generic implementation.

        Truncates based on self.max_message_size, formats with status line,
        and always edits existing message (creates new only if edit fails).

        Subclasses can override _build_output_metadata() for platform-specific formatting.
        """
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found, cannot send output update", session_id[:8])
            return None

        ux_state = await db.get_ux_state(session_id)

        # Check adapter_metadata for this adapter's message_id (for observers)
        # Origin adapter uses ux_state.output_message_id, observers use adapter_metadata
        adapter_metadata: dict[str, object] = session.adapter_metadata or {}
        adapter_key = self._get_adapter_key()  # e.g., "telegram", "redis"
        adapter_data_obj = adapter_metadata.get(adapter_key, {})
        adapter_data: dict[str, object] = adapter_data_obj if isinstance(adapter_data_obj, dict) else {}

        logger.debug(
            "[OBSERVER] session=%s adapter=%s checking message_id (adapter_data=%s, ux_state=%s)",
            session_id[:8],
            adapter_key,
            bool(adapter_data.get("output_message_id")),
            bool(ux_state.output_message_id),
        )

        # Prefer adapter-specific message_id, fallback to ux_state (for origin adapter)
        message_id_obj = adapter_data.get("output_message_id")
        current_message_id: Optional[str] = (
            message_id_obj if isinstance(message_id_obj, str) else None
        ) or ux_state.output_message_id

        # Truncate to platform limit
        is_truncated = len(output) > self.max_message_size
        terminal_output = output[-self.max_message_size :] if is_truncated else output

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

        # Format message (base + platform-specific formatting)
        display_output = self.format_message(terminal_output, status_line)

        # Platform-specific metadata (inline keyboards, etc.)
        metadata = self._build_output_metadata(session_id, is_truncated, ux_state)

        # Send or edit
        if current_message_id:
            success = await self.edit_message(
                session_id, current_message_id, display_output, metadata if metadata else None
            )
            if success:
                return current_message_id
            # Edit failed - clear stale message_id and send new
            logger.warning("Failed to edit message %s, clearing stale message_id and sending new", current_message_id)
            # Clear from both locations
            await db.update_ux_state(session_id, output_message_id=None)
            if adapter_key in adapter_metadata and isinstance(adapter_metadata[adapter_key], dict):
                adapter_data_dict = adapter_metadata[adapter_key]
                if isinstance(adapter_data_dict, dict) and "output_message_id" in adapter_data_dict:
                    adapter_data_dict["output_message_id"] = None
                    await db.update_session(session_id, adapter_metadata=adapter_metadata)

        new_id = await self.send_message(session_id, display_output, metadata if metadata else None)
        if new_id:
            # Store in ux_state (for origin adapter) AND adapter_metadata (for all adapters)
            await db.update_ux_state(session_id, output_message_id=new_id)

            # Also store in adapter_metadata for this adapter type
            if adapter_key not in adapter_metadata:
                adapter_metadata[adapter_key] = {}
            adapter_data_dict = adapter_metadata[adapter_key]
            if not isinstance(adapter_data_dict, dict):
                adapter_data_dict = {}
                adapter_metadata[adapter_key] = adapter_data_dict
            adapter_data_dict["output_message_id"] = new_id
            await db.update_session(session_id, adapter_metadata=adapter_metadata)

            logger.debug(
                "[OBSERVER] Stored message_id=%s for adapter=%s session=%s (in adapter_metadata)",
                new_id,
                adapter_key,
                session_id[:8],
            )
        return new_id

    def format_message(self, terminal_output: str, status_line: str) -> str:
        """Format message with terminal output and status line.

        Base implementation wraps output in code block and adds status line.
        Override in subclasses to apply additional formatting like shortening lines.

        Args:
            terminal_output: Terminal output text
            status_line: Status line text

        Returns:
            Formatted message text
        """
        message_parts = []
        if terminal_output:
            message_parts.append(f"```\n{terminal_output}\n```")
        message_parts.append(status_line)
        return "\n".join(message_parts)

    def _build_output_metadata(
        self, session_id: str, is_truncated: bool, ux_state: object
    ) -> Optional[dict[str, object]]:
        """Build platform-specific metadata for output messages.

        Override in subclasses to add inline keyboards, buttons, etc.

        Args:
            session_id: Session identifier
            is_truncated: Whether output was truncated
            ux_state: Current UX state (for checking Claude session, etc.)

        Returns:
            Platform-specific metadata dict, or None
        """
        return None  # Default: no metadata

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
            raw_output = output_file.read_text(encoding="utf-8") if output_file.exists() else ""

            # Strip ANSI codes and exit markers for display
            current_output = strip_ansi_codes(raw_output)
            current_output = strip_exit_markers(current_output)

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

    async def send_feedback(
        self,
        session_id: str,
        message: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> Optional[str]:
        """Send feedback message and mark for deletion on next user input.

        UI adapters override BaseAdapter's no-op to send temporary feedback messages
        that automatically clean up when the user sends their next input.

        Args:
            session_id: Session identifier
            message: Feedback message text
            metadata: Optional adapter-specific metadata (defaults to plain text)

        Returns:
            message_id of sent feedback message
        """
        # Send feedback message (plain text by default)
        message_id = await self.send_message(session_id, message, metadata=metadata or {"parse_mode": None})

        if message_id:
            # Mark feedback message for deletion when next input arrives
            await db.add_pending_deletion(session_id, message_id)
            logger.debug("Sent feedback message %s for session %s (marked for deletion)", message_id, session_id[:8])

        return message_id

    async def _pre_handle_user_input(self, session_id: str) -> None:
        """Called before handling user input - cleanup temporary messages."""
        await self.cleanup_feedback_messages(session_id)

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
        # Delegate to utility module
        await handle_voice(
            session_id=session_id,
            audio_path=audio_file_path,
            context=context,
            send_feedback=self.send_feedback,
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

        Delegates to session_utils for centralized path management.

        Args:
            session_id: Session identifier

        Returns:
            Path object pointing to local file (e.g., "workspace/abc123/tmux.txt")

        NOTE: This is different from get_session_file() which creates download UI.
        """
        return get_output_file(session_id)
