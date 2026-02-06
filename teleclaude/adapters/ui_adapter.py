"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionUpdatedContext, TeleClaudeEvents, UiCommands
from teleclaude.core.feedback import get_last_feedback
from teleclaude.core.models import (
    AdapterType,
    CleanupTrigger,
    MessageMetadata,
    SessionField,
    TelegramAdapterMetadata,
)
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.voice_message_handler import handle_voice

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

from teleclaude.utils import format_active_status_line, format_completed_status_line, format_size
from teleclaude.utils.markdown import telegramify_markdown

logger = get_logger(__name__)


class UiAdapter(BaseAdapter):
    """Base class for UI-enabled adapters.

    Provides output message management for platforms with editable messages.
    Subclasses can override max_message_size and add platform-specific formatting.
    """

    # Adapter key for metadata storage (subclasses MUST override)
    ADAPTER_KEY: str = "unknown"

    # Optional command handler overrides: command -> handler method name
    COMMAND_HANDLER_OVERRIDES: dict[str, str] = {}

    # Platform message size limit (subclasses can override)
    max_message_size: int = UI_MESSAGE_MAX_CHARS

    def __init__(self, client: "AdapterClient") -> None:
        """Initialize UiAdapter and register event listeners.

        Args:
            client: AdapterClient instance
        """
        # Set client (BaseAdapter has no __init__, just requires this attribute)
        self.client = client

        # Register event listeners
        event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated)

    # === Adapter Metadata Helpers ===

    async def ensure_channel(self, session: "Session", title: str) -> "Session":
        """Ensure adapter-specific channel exists (default no-op)."""
        _ = title
        return session

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
        logger.debug(
            "Stored output_message_id: session=%s message_id=%s",
            session.session_id[:8],
            message_id,
        )

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
        logger.debug(
            "Cleared output_message_id: session=%s",
            session.session_id[:8],
        )

    async def _try_edit_output_message(self, session: "Session", text: str, metadata: MessageMetadata) -> bool:
        """Try to edit existing output message, clear message_id if edit fails.

        Returns:
            True if edited successfully, False if no message_id or edit failed
        """
        message_id = await self._get_output_message_id(session)
        logger.debug(
            "[TRY_EDIT] session=%s existing_message_id=%s",
            session.session_id[:8],
            message_id if message_id else "None",
        )
        if not message_id:
            logger.debug("[TRY_EDIT] No existing message_id, will send new message")
            return False

        logger.debug("[TRY_EDIT] Attempting to edit message %s for session %s", message_id, session.session_id[:8])
        success = await self.edit_message(session, message_id, text, metadata=metadata)
        logger.debug(
            "[TRY_EDIT] Edit result for message %s: %s",
            message_id,
            "SUCCESS" if success else "FAILED",
        )

        if not success:
            # Edit failed - clear stale message_id
            logger.warning("[TRY_EDIT] Failed to edit message %s, clearing stale message_id", message_id)
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
                await self.client.send_message(
                    session,
                    f"❌ {error_message}",
                    metadata=self._metadata(),
                    cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
                )
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
            handler_name = self.COMMAND_HANDLER_OVERRIDES.get(command, f"_handle_{command}")
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
        render_markdown: bool = False,
    ) -> Optional[str]:
        """Send or edit output message - generic implementation.

        Truncates based on self.max_message_size, formats with status line,
        and always edits existing message (creates new only if edit fails).

        Subclasses can override _build_output_metadata() for platform-specific formatting.
        """
        from teleclaude.utils import strip_ansi_codes

        # Strip ANSI codes if configured
        if config.terminal.strip_ansi:
            output = strip_ansi_codes(output)

        # Truncate to platform limit
        is_truncated = len(output) > self.max_message_size
        tmux_output = output[-self.max_message_size :] if is_truncated else output

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

        # Build session ID lines for footer
        session_id_lines = self._build_session_id_lines(session)

        # Format message (base + platform-specific formatting)
        full_status = f"{session_id_lines}\n{status_line}" if session_id_lines else status_line
        if render_markdown:
            if is_truncated:
                prefix = f"[...truncated, showing last {self.max_message_size} chars...]"
                max_body = max(self.max_message_size - len(prefix) - 2, 0)
                tmux_output = output[-max_body:] if max_body else ""
                body = f"{prefix}\n\n{tmux_output}" if tmux_output else prefix
            else:
                body = tmux_output

            if body:
                display_output = f"{body}\n\n{full_status}"
            else:
                display_output = full_status

            if self.ADAPTER_KEY == AdapterType.TELEGRAM.value:
                display_output = telegramify_markdown(display_output)
        else:
            display_output = self.format_message(tmux_output, full_status)

        # Platform-specific metadata (inline keyboards, etc.)
        metadata = self._build_output_metadata(session, is_truncated)
        if render_markdown and not metadata.parse_mode:
            metadata.parse_mode = "MarkdownV2" if self.ADAPTER_KEY == AdapterType.TELEGRAM.value else "Markdown"

        # Try to edit existing message
        display_digest = sha256(display_output.encode("utf-8")).hexdigest()
        if session.last_output_digest == display_digest:
            logger.trace(
                "[UI_SEND_OUTPUT] Skipping update for session %s (content unchanged)",
                session.session_id[:8],
            )
            return await self._get_output_message_id(session)

        edit_result = await self._try_edit_output_message(session, display_output, metadata)
        logger.debug(
            "[UI_SEND_OUTPUT] Edit attempt for session %s: result=%s",
            session.session_id[:8],
            edit_result,
        )
        if edit_result:
            # Edit succeeded, return existing message_id
            message_id = await self._get_output_message_id(session)
            await db.update_session(session.session_id, last_output_digest=display_digest)
            logger.debug(
                "[UI_SEND_OUTPUT] Edit succeeded, message_id=%s for session %s",
                message_id,
                session.session_id[:8],
            )
            return message_id

        # Edit failed or no existing message - send new
        logger.info(
            "[UI_SEND_OUTPUT] Sending new message for session %s (edit_failed or no_existing_message)",
            session.session_id[:8],
        )
        new_id = await self.send_message(session, display_output, metadata=metadata)
        logger.info(
            "[UI_SEND_OUTPUT] send_message returned %s for session %s",
            new_id if new_id else "None (FAILED!)",
            session.session_id[:8],
        )
        if new_id:
            await self._store_output_message_id(session, new_id)
            await db.update_session(session.session_id, last_output_digest=display_digest)
        return new_id

    def format_message(self, tmux_output: str, status_line: str) -> str:
        """Format message with tmux output and status line.

        Base implementation wraps output in code block and adds status line.
        Override in subclasses to apply additional formatting like shortening lines.

        Args:
            tmux_output: Tmux output text
            status_line: Status line text

        Returns:
            Formatted message text
        """
        from teleclaude.utils.markdown import escape_markdown_v2

        message_parts = []
        if tmux_output:
            # Escape internal ``` markers to prevent nested code blocks breaking markdown
            # Use zero-width space (\u200b) to break the sequence
            sanitized = tmux_output.replace("```", "`\u200b``")
            message_parts.append(f"```\n{sanitized}\n```")
        # Escape status_line for MarkdownV2 (contains special chars like -, :, etc.)
        escaped_status = escape_markdown_v2(status_line)
        message_parts.append(escaped_status)
        return "\n".join(message_parts)

    def _build_output_metadata(self, _session: "Session", _is_truncated: bool) -> MessageMetadata:
        """Build platform-specific metadata for output messages.

        Override in subclasses to add inline keyboards, buttons, etc.

        Args:
            session: Session object
            is_truncated: Whether output was truncated

        Returns:
            Platform-specific MessageMetadata
        """
        return MessageMetadata()  # Default: no extra metadata

    def _build_session_id_lines(self, session: "Session") -> str:
        """Build session ID lines for status footer.

        Shows TeleClaude session ID and native agent session ID (if available).

        Args:
            session: Session object

        Returns:
            Formatted session ID lines (may be empty string if no IDs)
        """
        lines: list[str] = []

        # TeleClaude session ID (full UUID)
        if session.session_id:
            lines.append(f"📋 tc: {session.session_id}")

        # Native agent session ID (from session - set when any agent starts)
        if session.native_session_id:
            agent_name = session.active_agent or "ai"
            lines.append(f"🤖 {agent_name}: {session.native_session_id}")

        return "\n".join(lines)

    async def _pre_handle_user_input(self, _session: "Session") -> None:
        """Called before handling user input - cleanup ephemeral messages.

        All tracked messages (feedback, user input) cleaned here.
        """
        # User input messages (pending_deletions) cleaned via event handler, not here

    async def _dispatch_command(
        self,
        session: "Session",
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: dict[str, object],  # noqa: loose-dict - Command payload for observers
        handler: Callable[[], Awaitable[object]],
    ) -> object:
        """Run command with UI pre/post handling and observer broadcast."""
        if metadata.origin and metadata.origin in self.client.adapters:
            await db.update_session(session.session_id, last_input_origin=metadata.origin)

        if message_id:
            await self.client.pre_handle_command(session, metadata.origin)

        result = await handler()

        if command_name == "send_message":
            text_obj = payload.get("text")
            if text_obj is not None:
                await db.update_session(
                    session.session_id,
                    last_message_sent=str(text_obj)[:200],
                    last_message_sent_at=datetime.now(timezone.utc).isoformat(),
                )

        if message_id:
            await self.client.post_handle_command(session, message_id, metadata.origin)

        await self.client.broadcast_command_action(session, command_name, payload, metadata.origin)
        return result

    # ==================== Voice Support ====================

    async def _process_voice_input(
        self,
        session_id: str,
        audio_file_path: str,
        context: dict[str, object],  # noqa: loose-dict - Voice event context
    ) -> None:
        """Shared voice processing logic for UI adapters.

        Default implementation uses voice_message_handler.py utility.
        Override if platform needs custom voice handling.

        Flow:
        1. Validate session and check if process is running
        2. Send "Transcribing..." notice to user
        3. Transcribe audio using voice_message_handler.py
        4. Send transcribed text to tmux
        5. Send notice on success/failure

        Args:
            session_id: Session ID
            audio_file_path: Path to audio file (any format supported by Whisper)
            context: Platform-specific metadata (user_id, duration, etc.)
        """

        async def _send_notice(sid: str, message: str, metadata: MessageMetadata) -> Optional[str]:
            session = await db.get_session(sid)
            if not session:
                logger.warning("Session %s not found for message", sid[:8])
                return None
            return await self.client.send_message(
                session,
                message,
                metadata=metadata,
                cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
            )

        # Delegate to utility module
        await handle_voice(
            session_id=session_id,
            audio_path=audio_file_path,
            context=context,  # type: ignore[arg-type]
            send_message=_send_notice,
            delete_message=self._delete_message_by_session_id,
        )

    async def _delete_message_by_session_id(self, sid: str, message_id: str) -> None:
        session = await db.get_session(sid)
        if not session:
            logger.warning("Session %s not found for delete", sid[:8])
            return
        await self.delete_message(session, message_id)

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
        - title: Direct title update (from summary) → sync to UiAdapter instances
        - project_path/subdir: Path change → update path portion in title

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

        title_updated = False

        # Handle direct title update (from summary)
        if SessionField.TITLE.value in updated_fields:
            new_title = str(updated_fields[SessionField.TITLE.value])
            await self.client.update_channel_title(session, new_title)
            logger.info("Synced title to UiAdapters for session %s: %s", session_id[:8], new_title)
            title_updated = True

        # project_path/subdir update adjusts the path portion in the title
        if not title_updated and (
            SessionField.PROJECT_PATH.value in updated_fields or SessionField.SUBDIR.value in updated_fields
        ):
            project_path = str(updated_fields.get(SessionField.PROJECT_PATH.value) or session.project_path or "")
            subdir = str(updated_fields.get(SessionField.SUBDIR.value) or session.subdir or "")
            new_path = project_path
            if subdir:
                new_path = str(Path(project_path) / subdir)

            # Extract last 2 path components
            path_parts = Path(new_path).parts
            last_two = "/".join(path_parts[-2:]) if len(path_parts) >= 2 else path_parts[-1] if path_parts else ""

            # Parse old title and replace path portion in brackets
            # Title format: $ComputerName[old/path] - Description
            # We want: $ComputerName[new/path] - Description
            title_pattern = r"^(\$\w+\[)[^\]]+(\]\[.*)$"
            match = re.match(title_pattern, session.title)

            if not match:
                logger.warning(
                    "Session %s title doesn't match expected format '$Computer[path] - Description': %s. Skipping title update.",
                    session_id[:8],
                    session.title,
                )
            else:
                # Replace path portion in brackets
                new_title = f"{match.group(1)}{last_two}{match.group(2)}"

                # Update via client to distribute to all adapters
                await self.client.update_channel_title(session, new_title)
                logger.info("Updated title for session %s to: %s", session_id[:8], new_title)

        # Handle feedback output updates (check both raw and summary fields)
        feedback_updated = (
            SessionField.LAST_FEEDBACK_RECEIVED.value in updated_fields or "last_feedback_summary" in updated_fields
        )
        if feedback_updated and session.lifecycle_status != "headless":
            # Use helper to get appropriate feedback based on config
            feedback = get_last_feedback(session) or ""
            if feedback:
                logger.debug(
                    "Feedback emit: session=%s len=%d updated_fields=%s",
                    session_id[:8],
                    len(feedback),
                    list(updated_fields.keys()),
                )
                await self.client.send_message(
                    session,
                    feedback,
                    metadata=MessageMetadata(parse_mode=None),
                    cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
                )
