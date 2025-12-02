"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import (
    ClaudeEventContext,
    SessionUpdatedContext,
    TeleClaudeEvents,
    UiCommands,
)
from teleclaude.core.models import MessageMetadata, TelegramAdapterMetadata
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.voice_message_handler import handle_voice

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    format_terminal_message,
)

logger = logging.getLogger(__name__)


class UiAdapter(BaseAdapter):
    """Base class for UI-enabled adapters.

    Provides output message management for platforms with editable messages.
    Subclasses can override max_message_size and add platform-specific formatting.
    """

    # Adapter key for metadata storage (subclasses MUST override)
    ADAPTER_KEY: str = "unknown"

    # Platform message size limit (subclasses can override)
    # Default: 3900 chars (Telegram: 4096 limit - ~196 overhead)
    max_message_size: int = 3900

    def __init__(self, client: "AdapterClient") -> None:
        """Initialize UiAdapter and register event listeners.

        Args:
            client: AdapterClient instance
        """
        # Set client (BaseAdapter has no __init__, just requires this attribute)
        self.client = client

        # Register event listeners
        # Type ignore: event system guarantees correct context type for each event
        self.client.on(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated)  # type: ignore[arg-type]
        self.client.on(TeleClaudeEvents.CLAUDE_EVENT, self._handle_claude_event)  # type: ignore[arg-type]

    # === Adapter Metadata Helpers ===

    async def _get_output_message_id(self, session: "Session") -> Optional[str]:
        """Get output_message_id from adapter namespace.

        Returns:
            message_id or None if not set
        """
        metadata: Optional[TelegramAdapterMetadata] = getattr(session.adapter_metadata, self.ADAPTER_KEY, None)
        if not metadata:
            return None

        return metadata.output_message_id

    async def _store_output_message_id(self, session: "Session", message_id: str) -> None:
        """Store output_message_id in adapter namespace."""
        # Get or create adapter metadata
        metadata: Optional[TelegramAdapterMetadata] = getattr(session.adapter_metadata, self.ADAPTER_KEY, None)
        if not metadata:
            metadata = TelegramAdapterMetadata()
            setattr(session.adapter_metadata, self.ADAPTER_KEY, metadata)

        # Store message_id (type narrowed by if-check above)
        typed_metadata: TelegramAdapterMetadata = metadata
        typed_metadata.output_message_id = message_id
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

    async def _clear_output_message_id(self, session: "Session") -> None:
        """Clear output_message_id from adapter namespace."""
        # Get or create adapter metadata
        metadata: Optional[TelegramAdapterMetadata] = getattr(session.adapter_metadata, self.ADAPTER_KEY, None)
        if not metadata:
            metadata = TelegramAdapterMetadata()
            setattr(session.adapter_metadata, self.ADAPTER_KEY, metadata)

        # Clear message_id (type narrowed by if-check above)
        typed_metadata: TelegramAdapterMetadata = metadata
        typed_metadata.output_message_id = None
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

    async def _try_edit_output_message(self, session: "Session", text: str, metadata: MessageMetadata) -> bool:
        """Try to edit existing output message, clear message_id if edit fails.

        Returns:
            True if edited successfully, False if no message_id or edit failed
        """
        message_id = await self._get_output_message_id(session)
        if not message_id:
            return False

        success = await self.edit_message(session, message_id, text, metadata)

        if not success:
            # Edit failed - clear stale message_id
            logger.warning("Failed to edit message %s, clearing stale message_id", message_id)
            await self._clear_output_message_id(session)

        return success

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error as feedback message to user.

        Args:
            session_id: Session that encountered error
            error_message: Human-readable error description
        """
        try:
            session = await db.get_session(session_id)
            if session:
                await self.send_feedback(session, f"❌ {error_message}", self._metadata())
        except Exception as e:
            logger.error("Failed to send error feedback for session %s: %s", session_id, e)

    # === Command Registration ===

    def _get_command_handlers(self) -> list[tuple[str, object]]:
        """Get command handlers by convention: command_name → _handle_{command_name}.

        Returns:
            List of (command_name, handler_method) tuples
        """
        handlers: list[tuple[str, object]] = []
        for command, _ in UiCommands.items():
            handler_name = f"_handle_{command}"
            handler: object = getattr(self, handler_name, None)
            if handler:
                handlers.append((command, handler))
            else:
                logger.warning("Handler %s not found for command %s", handler_name, command)
        return handlers

    # === Output Message Management (Default Implementations) ===

    async def send_output_update(
        self,
        session: "Session",  # type: ignore[name-defined]
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
        ux_state = await db.get_ux_state(session.session_id)

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
        metadata = self._build_output_metadata(session, is_truncated, ux_state)

        # Try to edit existing message
        if await self._try_edit_output_message(session, display_output, metadata):
            # Edit succeeded, return existing message_id
            return await self._get_output_message_id(session)

        # Edit failed or no existing message - send new
        new_id = await self.send_message(session, display_output, metadata)
        if new_id:
            await self._store_output_message_id(session, new_id)
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
        self, session: "Session", is_truncated: bool, ux_state: object  # type: ignore[name-defined]
    ) -> MessageMetadata:
        """Build platform-specific metadata for output messages.

        Override in subclasses to add inline keyboards, buttons, etc.

        Args:
            session: Session object
            is_truncated: Whether output was truncated
            ux_state: Current UX state (for checking Claude session, etc.)

        Returns:
            Platform-specific MessageMetadata
        """
        return MessageMetadata()  # Default: no extra metadata

    async def send_exit_message(self, session: "Session", output: str, exit_text: str) -> None:
        """Send exit message when session dies - default implementation."""
        final_output = format_terminal_message(output if output else "", exit_text)
        metadata = MessageMetadata(raw_format=True)

        # Try to edit existing message, fallback to send new
        if not await self._try_edit_output_message(session, final_output, metadata):
            # send new
            new_id = await self.send_message(session, final_output, metadata)
            if new_id:
                await self._store_output_message_id(session, new_id)

    async def send_feedback(
        self,
        session: "Session",
        message: str,
        metadata: MessageMetadata,
    ) -> Optional[str]:
        """Send feedback message and mark for deletion on next user input.

        UI adapters override BaseAdapter's no-op to send temporary feedback messages
        that automatically clean up when the user sends their next input.

        Args:
            session: Session object
            message: Feedback message text
            metadata: Adapter-specific metadata

        Returns:
            message_id of sent feedback message
        """
        # Send feedback message (plain text by default)
        message_id = await self.send_message(session, message, metadata=metadata or MessageMetadata(parse_mode=""))

        if message_id:
            # Mark feedback message for deletion when next input arrives
            await db.add_pending_deletion(session.session_id, message_id)
            logger.debug(
                "Sent feedback message %s for session %s (marked for deletion)", message_id, session.session_id[:8]
            )

        return message_id

    async def _pre_handle_user_input(self, session: "Session") -> None:
        """Called before handling user input - cleanup temporary messages."""
        await self.cleanup_feedback_messages(session)

    async def cleanup_feedback_messages(self, session: "Session") -> None:
        """Delete temporary feedback messages - default implementation."""
        ux_state = await db.get_ux_state(session.session_id)
        pending_deletions = ux_state.pending_deletions or []

        if not pending_deletions:
            return

        for message_id in pending_deletions:
            try:
                await self.delete_message(session, message_id)
                logger.debug("Deleted feedback message %s for session %s", message_id, session.session_id[:8])
            except Exception as e:
                logger.warning("Failed to delete message %s: %s", message_id, e)

        # Clear pending deletions
        await db.update_ux_state(session.session_id, pending_deletions=[])

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

    # ==================== Event Handlers ====================

    async def _handle_session_updated(self, event: str, context: SessionUpdatedContext) -> None:
        """Handle session_updated event - update channel title when working directory changes.

        Args:
            event: Event type
            context: Typed session updated context
        """
        session_id = context.session_id
        updated_fields = context.updated_fields or {}

        # Get old session to check what changed
        session = await db.get_session(session_id)
        if not session:
            return

        # Check if working_directory changed
        if "working_directory" not in updated_fields:
            return

        # working_directory was updated - session is already updated in db
        new_path = str(updated_fields["working_directory"])

        # Extract last 2 path components
        path_parts = Path(new_path).parts
        last_two = "/".join(path_parts[-2:]) if len(path_parts) >= 2 else path_parts[-1] if path_parts else ""

        # Parse old title and replace path portion in brackets
        # Title format: $ComputerName[old/path] - Description
        # We want: $ComputerName[new/path] - Description
        title_pattern = r"^(\$\w+\[)[^\]]+(\].*)$"
        match = re.match(title_pattern, session.title)

        if not match:
            logger.warning(
                "Session %s title doesn't match expected format '$Computer[path] - Description': %s. Skipping title update.",
                session_id[:8],
                session.title,
            )
            return

        # Replace path portion in brackets
        new_title = f"{match.group(1)}{last_two}{match.group(2)}"

        # Update via client to distribute to all adapters
        await self.client.update_channel_title(session, new_title)
        logger.info("Updated title for session %s to: %s", session_id[:8], new_title)

    async def _handle_claude_event(self, event: str, context: ClaudeEventContext) -> None:
        """Dispatch claude_event to appropriate handler based on event_type.

        Args:
            event: Event type
            context: Typed Claude event context
        """
        if not context.event_type:
            return

        # Dispatch to specific handler
        if context.event_type == "session_start":
            await self._handle_claude_session_start(context)
        elif context.event_type == "stop":
            await self._handle_claude_stop(context)

    async def _handle_claude_session_start(self, context: ClaudeEventContext) -> None:
        """Handle session_start event - store claude_session_id and claude_session_file.

        Args:
            context: Typed Claude event context
        """

        claude_session_id = context.data.get("session_id")
        claude_session_file = context.data.get("transcript_path")

        if not claude_session_id or not claude_session_file:
            return

        await db.update_ux_state(
            context.session_id,
            claude_session_id=str(claude_session_id),
            claude_session_file=str(claude_session_file),
        )
        logger.info(
            "Stored Claude session data: teleclaude=%s, claude=%s",
            context.session_id[:8],
            str(claude_session_id)[:8],
        )

    async def _handle_claude_stop(self, context: ClaudeEventContext) -> None:
        """Handle stop event - update channel title from Claude-generated title.

        Args:
            context: Typed Claude event context
        """
        session_id = context.session_id

        # Get claude_session_file from ux_state
        ux_state = await db.get_ux_state(session_id)
        if not ux_state.claude_session_file:
            logger.debug("No claude_session_file for session %s, skipping title update", session_id[:8])
            return

        # Parse session file for latest title
        claude_title = await self._extract_claude_title(ux_state.claude_session_file)
        if not claude_title:
            logger.debug("No title found in claude_session_file for session %s", session_id[:8])
            return

        # Get and validate session
        session = await self._get_session(session_id)

        # Parse current title and replace description part
        # Title format: $ComputerName[path] - OLD_DESCRIPTION
        # We want: $ComputerName[path] - CLAUDE_TITLE
        title_pattern = r"^(\$\w+\[[^\]]+\] - ).*$"
        match = re.match(title_pattern, session.title)

        if not match:
            logger.warning(
                "Session %s title doesn't match expected format '$Computer[path] - Description': %s. Skipping title update.",
                session_id[:8],
                session.title,
            )
            return

        # Replace description portion
        new_title = f"{match.group(1)}{claude_title}"

        # Update via client to distribute to all adapters
        await self.client.update_channel_title(session, new_title)
        logger.info("Updated Claude title for session %s to: %s", session_id[:8], new_title)

    async def _extract_claude_title(self, session_file_path: str) -> Optional[str]:
        """Extract AI-generated title from Claude session file.

        Args:
            session_file_path: Path to Claude session .jsonl file

        Returns:
            Extracted title or None
        """
        session_file = Path(session_file_path).expanduser()
        if not session_file.exists():
            return None

        try:
            # Read file backwards to find most recent summary entry
            with open(session_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Parse lines in reverse to find latest summary
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry_obj: object = json.loads(line)  # JSON returns Any
                    # Narrow type: entry should be dict
                    if not isinstance(entry_obj, dict):
                        continue
                    entry: dict[str, object] = entry_obj
                    entry_type: object = entry.get("type")
                    if entry_type == "summary" and "title" in entry:
                        title_obj: object = entry["title"]
                        return str(title_obj) if title_obj is not None else None
                except json.JSONDecodeError:
                    continue

            return None

        except Exception as e:
            logger.error("Failed to extract Claude title from %s: %s", session_file_path, e)
            return None
