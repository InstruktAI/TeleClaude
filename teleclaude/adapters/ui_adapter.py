"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import base64
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
from teleclaude.core.session_listeners import get_listeners
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.terminal_bridge import send_keys
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

    # === User Input Formatting ===

    def format_user_input(self, text: str) -> str:
        """Format incoming user input with HUMAN: prefix.

        This distinguishes human messages from AI messages (which use AI[computer:session_id] prefix).
        All UI adapters should call this when processing user text input before sending to daemon.

        Args:
            text: Raw user input text

        Returns:
            Prefixed text: "HUMAN: {text}"
        """
        return f"HUMAN: {text}"

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

    async def send_output_update(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        session: "Session",
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
            # Escape internal ``` markers to prevent nested code blocks breaking markdown
            # Use zero-width space (\u200b) to break the sequence
            sanitized = terminal_output.replace("```", "`\u200b``")
            message_parts.append(f"```\n{sanitized}\n```")
        message_parts.append(status_line)
        return "\n".join(message_parts)

    def _build_output_metadata(self, _session: "Session", _is_truncated: bool, _ux_state: object) -> MessageMetadata:
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
        persistent: bool = False,
    ) -> Optional[str]:
        """Send feedback message, optionally cleaning up previous feedback first.

        UI adapters override BaseAdapter's no-op to send temporary feedback messages.

        Args:
            session: Session object
            message: Feedback message text
            metadata: Adapter-specific metadata
            persistent: If True, skip cleanup (don't delete previous feedback).
                       Message is STILL added to pending_feedback_deletions for future cleanup.

        Returns:
            message_id of sent feedback message
        """
        # Only cleanup previous feedback if not persistent
        # Notifications (persistent=True) don't trigger cleanup but still get added to deletion list
        # Summary (persistent=False) cleans up notifications, then adds itself
        if not persistent:
            await self.cleanup_feedback_messages(session)

        # Send feedback message (plain text by default)
        message_id = await self.send_message(session, message, metadata=metadata or MessageMetadata(parse_mode=""))

        if message_id:
            # Always add to pending_feedback_deletions (even persistent messages)
            # This ensures next non-persistent feedback will clean them up
            await db.add_pending_feedback_deletion(session.session_id, message_id)
            logger.debug(
                "Sent feedback message %s for session %s (marked for feedback deletion)",
                message_id,
                session.session_id[:8],
            )

        return message_id

    async def _pre_handle_user_input(self, _session: "Session") -> None:
        """Called before handling user input - cleanup user input messages only.

        Note: Feedback messages (pending_feedback_deletions) are cleaned up in send_feedback,
        not here. This ensures download messages stay until the next feedback (like summary).
        """
        # User input messages (pending_deletions) cleaned via event handler, not here

    async def cleanup_feedback_messages(self, session: "Session") -> None:
        """Delete temporary feedback messages - default implementation."""
        ux_state = await db.get_ux_state(session.session_id)
        pending_feedback = ux_state.pending_feedback_deletions or []

        if not pending_feedback:
            return

        for message_id in pending_feedback:
            try:
                await self.delete_message(session, message_id)
                logger.debug("Deleted feedback message %s for session %s", message_id, session.session_id[:8])
            except Exception as e:
                logger.warning("Failed to delete message %s: %s", message_id, e)

        # Clear pending feedback deletions
        await db.update_ux_state(session.session_id, pending_feedback_deletions=[])

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
            context=context,  # type: ignore[arg-type]
            send_feedback=self.send_feedback,  # type: ignore[arg-type]
        )

    # ==================== File Handling ====================

    async def get_session_file(
        self,
        _session_id: str,
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

    async def _handle_session_updated(self, _event: str, context: SessionUpdatedContext) -> None:
        """Handle session_updated event - update channel title when fields change.

        Handles:
        - title: Direct title update (from summary) → sync to Telegram
        - working_directory: Path change → update path portion in title

        Args:
            event: Event type
            context: Typed session updated context
        """
        session_id = context.session_id
        updated_fields = context.updated_fields or {}

        # Get session (already updated in DB)
        session = await db.get_session(session_id)
        if not session:
            return

        # Handle direct title update (from summary)
        if "title" in updated_fields:
            new_title = str(updated_fields["title"])
            await self.client.update_channel_title(session, new_title)
            logger.info("Synced title to Telegram for session %s: %s", session_id[:8], new_title)
            return  # Title already includes everything, skip working_directory handling

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

    async def _handle_claude_event(self, _event: str, context: ClaudeEventContext) -> None:
        """Dispatch claude_event to appropriate handler based on event_type.

        Args:
            event: Event type
            context: Typed Claude event context
        """
        if not context.event_type:
            return

        # Dispatch to specific handler
        # Note: "stop" event now contains title/summary from bridge hook (single enriched event)
        if context.event_type == "session_start":
            await self._handle_claude_session_start(context)
        elif context.event_type == "stop":
            await self._handle_claude_stop(context)
        elif context.event_type == "notification":
            await self._handle_notification(context)
        elif context.event_type == "title_update":
            await self._handle_title_update(context)

    async def _handle_claude_session_start(self, context: ClaudeEventContext) -> None:
        """Handle session_start event - store claude_session_id, claude_session_file, and copy voice.

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

        # Copy voice assignment from teleclaude session_id to claude_session_id
        # This allows voice to persist even if tmux session is destroyed and recreated
        voice = await db.get_voice(context.session_id)
        if voice:
            await db.assign_voice(str(claude_session_id), voice)
            logger.debug("Copied voice '%s' to claude_session_id %s", voice.name, str(claude_session_id)[:8])

        logger.info(
            "Stored Claude session data: teleclaude=%s, claude=%s",
            context.session_id[:8],
            str(claude_session_id)[:8],
        )

    async def _handle_claude_stop(self, context: ClaudeEventContext) -> None:
        """Handle stop event - Claude Code session stopped (enriched with title/summary).

        This is the SINGLE event that handles everything:
        1. Notify local listeners (AI-to-AI on same computer)
        2. Forward to remote initiator (AI-to-AI across computers)
        3. Send summary feedback to Telegram
        4. Update session title in DB

        The bridge hook runs the summarizer BEFORE sending this event, so all data
        (title, summary) is already included in context.data.

        Args:
            context: Typed Claude event context with optional title/summary
        """
        session_id = context.session_id
        title = str(context.data.get("title", "")) if context.data.get("title") else None
        summary = str(context.data.get("summary", "")) if context.data.get("summary") else None

        logger.debug(
            "Claude stop event for session %s (title: %s, summary: %s)",
            session_id[:8],
            title[:20] if title else "none",
            summary[:20] if summary else "none",
        )

        # 1. Check for local listeners and notify callers (pass title for notification)
        await self._notify_session_listener(session_id, title=title)

        # 2. For remote-initiated sessions, forward stop event to the initiator's computer
        await self._forward_stop_to_initiator(session_id, title=title)

        # 3. Send summary as non-persistent feedback to Telegram (if available)
        if summary:
            session = await self._get_session(session_id)
            await self.send_feedback(session, summary, MessageMetadata(), persistent=False)
            logger.debug("Sent summary for session %s: %s", session_id[:8], summary[:50])

        # 4. Update session title in DB if provided
        if title:
            await self._update_session_title(session_id, title)

    async def _update_session_title(self, session_id: str, title: str) -> None:
        """Update session title in DB from AI-generated title.

        Only updates if the current title still has the default "New session" description.
        This ensures we only set the title once and don't overwrite user customizations.

        Args:
            session_id: Session to update
            title: New title from summarizer
        """
        session = await self._get_session(session_id)

        # Only update if title still has default "New session" or "New session (N)" description
        if not re.search(r"New session( \(\d+\))?$", session.title):
            logger.debug(
                "Session %s already has custom title, skipping update: %s",
                session_id[:8],
                session.title,
            )
            return

        # Parse current title and replace description part
        title_pattern = r"^(\$\w+\[[^\]]+\] - ).*$"
        match = re.match(title_pattern, session.title)

        if match:
            new_title = f"{match.group(1)}{title}"
            # Update DB - this triggers SESSION_UPDATED which calls update_channel_title
            await db.update_session(session_id, title=new_title)
            logger.info("Updated session title in DB for %s: %s", session_id[:8], new_title)
        else:
            logger.warning(
                "Session %s title doesn't match expected format: %s. Skipping title update.",
                session_id[:8],
                session.title,
            )

    async def _handle_title_update(self, context: ClaudeEventContext) -> None:
        """Handle title_update event - update channel title from AI-generated title.

        Only updates if the current title still has the default "New session" description.
        This ensures we only set the title once and don't overwrite user customizations.

        Args:
            context: Typed Claude event context with title in data
        """
        session_id = context.session_id
        title = context.data.get("title")

        if not title:
            logger.debug("No title in title_update event for session %s", session_id[:8])
            return

        # Get and validate session
        session = await self._get_session(session_id)

        # Only update if title still has default "New session" or "New session (N)" description
        if not re.search(r"New session( \(\d+\))?$", session.title):
            logger.debug(
                "Session %s already has custom title, skipping update: %s",
                session_id[:8],
                session.title,
            )
            return

        # Parse current title and replace description part
        # Title format: $ComputerName[path] - OLD_DESCRIPTION
        # We want: $ComputerName[path] - NEW_TITLE
        title_pattern = r"^(\$\w+\[[^\]]+\] - ).*$"
        match = re.match(title_pattern, session.title)

        if not match:
            logger.warning(
                "Session %s title doesn't match expected format: %s. Skipping title update.",
                session_id[:8],
                session.title,
            )
            return

        # Replace description portion
        new_title = f"{match.group(1)}{title}"

        # Update via client to distribute to all adapters
        await self.client.update_channel_title(session, new_title)
        logger.info("Updated title for session %s to: %s", session_id[:8], new_title)

    async def _handle_notification(self, context: ClaudeEventContext) -> None:
        """Handle notification event - notify listeners and send feedback to Telegram.

        When Claude asks a question (AskUserQuestion) or needs input, we:
        1. Forward the question to any registered listeners (calling AIs)
        2. Forward to remote initiator for cross-computer AI-to-AI sessions
        3. Send friendly feedback message to Telegram

        Args:
            context: Typed Claude event context with message and original_message in data
        """
        session_id = context.session_id
        friendly_message = context.data.get("message")
        original_message = context.data.get("original_message")

        if not friendly_message:
            logger.debug("No message in notification event for session %s", session_id[:8])
            return

        # 1. Notify local listeners with the ORIGINAL message (the actual question)
        if original_message:
            await self._forward_notification_to_listeners(session_id, str(original_message))

        # 2. Forward to remote initiator for cross-computer sessions
        if original_message:
            await self._forward_notification_to_initiator(session_id, str(original_message))

        # 3. Send friendly feedback to Telegram
        session = await self._get_session(session_id)
        await self.send_feedback(session, str(friendly_message), MessageMetadata(), persistent=True)

        # Set notification_sent flag (prevents duplicate idle notifications)
        await db.set_notification_flag(session_id, True)

        logger.debug("Sent notification for session %s: %s", session_id[:8], str(friendly_message)[:50])

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

    async def _notify_session_listener(self, target_session_id: str, *, title: str | None = None) -> None:
        """Notify all callers that a target session's Claude finished its turn.

        Uses get_listeners (not pop) because listeners stay active until session closes.
        "Stop" means Claude finished its turn, not that the session ended.

        Args:
            target_session_id: The session whose Claude finished its turn
            title: Optional AI-generated title from summarizer (preferred over DB title)
        """
        listeners = get_listeners(target_session_id)
        if not listeners:
            return

        # Get target session info for the notification
        # Prefer AI-generated title from stop event over DB title (which may not be updated yet)
        target_session = await db.get_session(target_session_id)
        display_title = title or (target_session.title if target_session else "Unknown")

        for listener in listeners:
            # Build notification message with title in quotes for clarity
            title_part = f' "{display_title}"' if title else f" ({display_title})"
            notification = (
                f"Session {target_session_id[:8]}{title_part} finished its turn. "
                f"Use teleclaude__get_session_data(computer='local', session_id='{target_session_id}') to inspect."
            )

            # Inject into caller's tmux session
            success, error = await send_keys(
                session_name=listener.caller_tmux_session,
                text=notification,
                send_enter=True,
            )

            if success:
                logger.info(
                    "Notified caller %s about target %s completion",
                    listener.caller_session_id[:8],
                    target_session_id[:8],
                )
            else:
                logger.warning(
                    "Failed to notify caller %s: %s",
                    listener.caller_session_id[:8],
                    error,
                )

    async def _forward_stop_to_initiator(self, session_id: str, *, title: str | None = None) -> None:
        """Forward stop event to the initiator's computer for remote-initiated sessions.

        For AI-to-AI sessions started via teleclaude__start_session, the session's
        adapter_metadata.redis.target_computer contains the initiator's computer name.
        We forward the stop event to that computer so their listener can fire.

        Args:
            session_id: The session that just stopped
            title: Optional title from summarizer to include in notification
        """
        session = await db.get_session(session_id)
        if not session:
            return

        # Check if this was a remote-initiated session
        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer

        # Don't forward to self (in case of misconfiguration)
        if initiator_computer == config.computer.name:
            return

        logger.info(
            "Forwarding stop event to initiator %s for session %s",
            initiator_computer,
            session_id[:8],
        )

        # Send stop_notification command to initiator's computer
        # The command includes the session_id, source computer, and optional title
        # Title is base64-encoded to safely pass through command parsing (may contain spaces)
        title_arg = ""
        if title:
            title_b64 = base64.b64encode(title.encode()).decode()
            title_arg = f" {title_b64}"

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/stop_notification {session_id} {config.computer.name}{title_arg}",
                metadata=MessageMetadata(),
            )
        except Exception as e:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, e)

    async def _forward_notification_to_listeners(self, target_session_id: str, message: str) -> None:
        """Forward a notification (question/input request) to all registered listeners.

        Unlike stop events, notifications don't remove listeners - the session is still active
        and asking a question. Listeners stay registered until the session actually stops.

        Args:
            target_session_id: The session that's asking the question
            message: The original notification message (question content)
        """
        listeners = get_listeners(target_session_id)
        if not listeners:
            return

        for listener in listeners:
            # Build notification message that lets the calling AI know it needs to respond
            notification = (
                f"Session {target_session_id[:8]} needs input: {message} "
                f"Use teleclaude__send_message(computer='local', session_id='{target_session_id}', "
                f"message='your response') to respond."
            )

            # Inject into caller's tmux session
            success, error = await send_keys(
                session_name=listener.caller_tmux_session,
                text=notification,
                send_enter=True,
            )

            if success:
                logger.info(
                    "Forwarded notification from %s to listener %s",
                    target_session_id[:8],
                    listener.caller_session_id[:8],
                )
            else:
                logger.warning(
                    "Failed to forward notification to listener %s: %s",
                    listener.caller_session_id[:8],
                    error,
                )

    async def _forward_notification_to_initiator(self, session_id: str, message: str) -> None:
        """Forward notification event to the initiator's computer for remote-initiated sessions.

        For AI-to-AI sessions started via teleclaude__start_session, the session's
        adapter_metadata.redis.target_computer contains the initiator's computer name.
        We forward the notification so the initiator can respond to questions.

        Args:
            session_id: The session asking the question
            message: The original notification message (question content)
        """
        session = await db.get_session(session_id)
        if not session:
            return

        # Check if this was a remote-initiated session
        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer

        # Don't forward to self (in case of misconfiguration)
        if initiator_computer == config.computer.name:
            return

        logger.info(
            "Forwarding notification to initiator %s for session %s",
            initiator_computer,
            session_id[:8],
        )

        # Send input_notification command to initiator's computer
        # Message is base64-encoded to safely pass through command parsing (may contain spaces)
        message_b64 = base64.b64encode(message.encode()).decode()

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/input_notification {session_id} {config.computer.name} {message_b64}",
                metadata=MessageMetadata(),
            )
        except Exception as e:
            logger.warning("Failed to forward notification to %s: %s", initiator_computer, e)
