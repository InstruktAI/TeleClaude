"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import asyncio
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
from teleclaude.core.feature_flags import is_threaded_output_enabled_for_session
from teleclaude.core.feedback import get_last_output_summary
from teleclaude.core.models import (
    CleanupTrigger,
    MessageMetadata,
    SessionField,
)
from teleclaude.core.session_utils import get_display_title_for_session, get_output_file
from teleclaude.core.voice_message_handler import handle_voice
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    strip_ansi_codes,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

from teleclaude.utils.markdown import (
    MarkdownV2State,
    continuation_prefix_for_markdown_v2_state,
    scan_markdown_v2_state,
    truncate_markdown_v2_with_consumed,
)

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

    # Per-session lock to serialize output delivery and prevent concurrent
    # lanes from racing on output_message_id reads/writes.
    _output_delivery_locks: dict[str, asyncio.Lock] = {}

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

    async def recover_lane_error(
        self,
        session: "Session",
        error: Exception,
        task_factory: Callable[["UiAdapter", "Session"], Awaitable[object]],
        display_title: str,
    ) -> object | None:
        """Attempt platform-specific recovery from a lane task error.

        Returns the task result if recovery succeeded, or None on recovery failure.
        Default: re-raises (no recovery available).
        """
        raise error

    async def _get_output_message_id(self, session: "Session") -> Optional[str]:
        """Get output_message_id from top-level DB column.

        Always re-reads from DB to prevent stale in-memory values when
        concurrent UI lanes deliver output for the same session.

        Returns:
            message_id or None if not set
        """
        fresh = await db.get_session(session.session_id)
        if fresh:
            session.output_message_id = fresh.output_message_id
        return session.output_message_id

    async def _store_output_message_id(self, session: "Session", message_id: str) -> None:
        """Store output_message_id in dedicated DB column.

        Uses atomic column write (not adapter_metadata blob) to prevent
        concurrent adapter_metadata writes from clobbering the value.
        """
        await db.set_output_message_id(session.session_id, message_id)
        session.output_message_id = message_id  # Keep in-memory session consistent
        logger.debug(
            "Stored output_message_id: session=%s message_id=%s",
            session.session_id[:8],
            message_id,
        )

    async def _get_footer_message_id(self, session: "Session") -> Optional[str]:
        """Get threaded footer message id from adapter namespace."""
        if self.ADAPTER_KEY == "telegram":
            metadata = session.get_metadata().get_ui().get_telegram()
            return metadata.footer_message_id
        return None

    async def _store_footer_message_id(self, session: "Session", message_id: str) -> None:
        """Store threaded footer message id in adapter namespace."""
        if self.ADAPTER_KEY == "telegram":
            metadata = session.get_metadata().get_ui().get_telegram()
            metadata.footer_message_id = message_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            logger.debug(
                "Stored footer_message_id: session=%s message_id=%s",
                session.session_id[:8],
                message_id,
            )

    async def _clear_footer_message_id(self, session: "Session") -> None:
        """Clear threaded footer message id from adapter namespace."""
        if self.ADAPTER_KEY == "telegram":
            metadata = session.get_metadata().get_ui().get_telegram()
            metadata.footer_message_id = None
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            logger.debug("Cleared footer_message_id: session=%s", session.session_id[:8])

    async def _cleanup_footer_if_present(self, session: "Session") -> None:
        """Delete and clear any tracked threaded footer message."""
        previous_footer_id = await self._get_footer_message_id(session)
        if not previous_footer_id:
            return
        try:
            await self.delete_message(session, previous_footer_id)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            logger.debug(
                "Best-effort stale threaded footer delete failed: session=%s message_id=%s err=%s",
                session.session_id[:8],
                previous_footer_id,
                exc,
            )
        finally:
            await self._clear_footer_message_id(session)

    async def _clear_output_message_id(self, session: "Session") -> None:
        """Clear output_message_id in dedicated DB column.

        Uses atomic column write (not adapter_metadata blob) to prevent
        concurrent adapter_metadata writes from clobbering the value.
        """
        await db.set_output_message_id(session.session_id, None)
        session.output_message_id = None  # Keep in-memory session consistent
        logger.debug(
            "Cleared output_message_id: session=%s",
            session.session_id[:8],
        )

    async def _deliver_output(
        self,
        session: "Session",
        text: str,
        metadata: MessageMetadata,
        multi_message: bool = False,
        status_line: str = "",
    ) -> Optional[str]:
        """Unified output delivery: dedup, edit/send, footer management.

        Serialized per session to prevent concurrent UI lanes from racing
        on output_message_id reads/writes (which creates duplicate messages).
        """
        sid = session.session_id
        if sid not in self._output_delivery_locks:
            self._output_delivery_locks[sid] = asyncio.Lock()

        async with self._output_delivery_locks[sid]:
            # 1. Digest-based dedup
            display_digest = sha256(text.encode("utf-8")).hexdigest()
            if session.last_output_digest == display_digest:
                return await self._get_output_message_id(session)

            # 2. Try edit existing
            if await self._try_edit_output_message(session, text, metadata):
                await db.update_session(session.session_id, last_output_digest=display_digest)
                await self._send_footer(session, status_line=status_line)
                return await self._get_output_message_id(session)

            # 3. Edit failed → cleanup footer, send new, send footer below
            await self._cleanup_footer_if_present(session)
            new_id = await self.send_message(session, text, metadata=metadata, multi_message=multi_message)
            if new_id:
                await self._store_output_message_id(session, new_id)
                await db.update_session(session.session_id, last_output_digest=display_digest)
                await self._send_footer(session, status_line=status_line)
            return new_id

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

    def _convert_markdown_for_platform(self, text: str) -> str:
        """Convert markdown to platform-specific format. Override for platform escaping."""
        return text

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        """Build output message within platform limits. Override for platform-specific fitting."""
        return self.format_output(tmux_output)

    @staticmethod
    def _fits_budget(text: str, max_bytes: int) -> bool:
        """Check if text fits within both char and byte budgets."""
        return len(text.encode("utf-8")) <= max_bytes

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
        # Suppress standard poller output when threaded output experiment is enabled.
        if is_threaded_output_enabled_for_session(session):
            logger.debug(
                "[UI_SEND_OUTPUT] Standard output suppressed for session %s (threaded output experiment active)",
                session.session_id[:8],
            )
            return None

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

        # Format output (tmux only; status line goes in footer)
        if render_markdown:
            if is_truncated:
                prefix = f"[...truncated, showing last {self.max_message_size} chars...]"
                max_body = max(self.max_message_size - len(prefix) - 2, 0)
                tmux_output = output[-max_body:] if max_body else ""
                display_output = f"{prefix}\n\n{tmux_output}" if tmux_output else prefix
            else:
                display_output = tmux_output

            display_output = self._convert_markdown_for_platform(display_output)
        else:
            display_output = self._fit_output_to_limit(tmux_output)

        # Platform-specific metadata (inline keyboards, etc.)
        metadata = self._build_output_metadata(session, is_truncated)

        return await self._deliver_output(session, display_output, metadata, status_line=status_line)

    async def send_threaded_output(
        self,
        session: "Session",
        text: str,
        multi_message: bool = False,
        _continuation_state: MarkdownV2State = (False, False, False),
    ) -> Optional[str]:
        """Send or edit threaded output message with smart pagination.

        Handles message length limits by splitting into multiple messages
        with "..." continuity markers.
        """
        # 1. Get current offset and ID
        char_offset = session.char_offset
        output_message_id = session.output_message_id

        # 2. Slice text to get the "active" portion
        # If text is shorter than offset (e.g. restart?), reset offset
        if len(text) < char_offset:
            char_offset = 0
            session.char_offset = 0
            await db.update_session(session.session_id, char_offset=0)

        active_text = text[char_offset:]
        if not active_text and output_message_id:
            # No new text, nothing to do
            return output_message_id

        # 3. Add continuity markers (escaped for MarkdownV2 when parse_mode requires it)
        is_markup_v2 = self._build_metadata_for_thread().parse_mode == "MarkdownV2"
        ellipsis = "\\.\\.\\." if is_markup_v2 else "..."
        continuation_prefix = continuation_prefix_for_markdown_v2_state(_continuation_state) if is_markup_v2 else ""
        body_text = f"{continuation_prefix}{active_text}"
        display_text = body_text
        prefix = ""
        if char_offset > 0:
            prefix = f"{ellipsis} "
            display_text = f"{prefix}{body_text}"

        # 4. Check for overflow
        # Reserve space for suffix " <ellipsis>" if needed
        limit = self.max_message_size - 10

        if len(display_text) > limit:
            # --- OVERFLOW: SEAL AND SPLIT ---

            # Calculate how much actual text fits (subtracting prefix)
            suffix = f" {ellipsis}"
            available_for_content = limit - len(prefix) - len(suffix)
            if available_for_content <= 0:
                available_for_content = 1

            if is_markup_v2:
                # Threaded mode receives MarkdownV2 text from coordinator.
                # Use the shared truncation helper to avoid slicing inside escapes/entities.
                chunk, consumed_display = truncate_markdown_v2_with_consumed(
                    body_text,
                    max_chars=available_for_content,
                    suffix="",
                )
                consumed_prefix = min(consumed_display, len(continuation_prefix))
                split_idx = consumed_display - consumed_prefix
                if split_idx <= 0 and active_text:
                    # Ensure forward progress under pathological inputs.
                    split_idx = min(len(active_text), available_for_content)
                    chunk, _ = truncate_markdown_v2_with_consumed(
                        f"{continuation_prefix}{active_text[:split_idx]}",
                        max_chars=available_for_content,
                        suffix="",
                    )
                consumed_source = active_text[:split_idx]
                next_state = scan_markdown_v2_state(consumed_source, initial_state=_continuation_state)
            else:
                # Find split point (smart truncate on space)
                candidate = active_text[:available_for_content]
                last_space = candidate.rfind(" ")
                if last_space > (len(candidate) * 0.8):  # Only split on space if it's near the end
                    split_idx = last_space
                else:
                    split_idx = available_for_content  # Hard split if no good space
                chunk = active_text[:split_idx]
                next_state = _continuation_state
            sealed_text = f"{prefix}{chunk}{suffix}"

            # Clean up footer before sealing so it doesn't sit between sealed and new message
            await self._cleanup_footer_if_present(session)

            # Commit this chunk
            seal_metadata = self._build_metadata_for_thread()
            if output_message_id:
                await self._try_edit_output_message(session, sealed_text, seal_metadata)
            else:
                new_id = await self.send_message(
                    session, sealed_text, metadata=seal_metadata, multi_message=multi_message
                )
                if new_id:
                    await self._store_output_message_id(session, new_id)
                    await self._send_footer(session)

            # Update state for next message
            new_offset = char_offset + split_idx
            session.char_offset = new_offset
            await db.update_session(session.session_id, char_offset=new_offset)
            # Clear output_message_id via dedicated column (not adapter_metadata blob)
            await db.set_output_message_id(session.session_id, None)
            session.output_message_id = None  # Keep in-memory session consistent

            # Recursive call to handle the remainder
            return await self.send_threaded_output(
                session,
                text,
                multi_message,
                _continuation_state=next_state,
            )

        # --- NORMAL CASE: FIT AND SEND ---
        metadata = self._build_metadata_for_thread()
        return await self._deliver_output(session, display_text, metadata, multi_message=multi_message)

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Build metadata for threaded content messages. Override for platform-specific parse mode."""
        return MessageMetadata()

    async def _send_footer(self, session: "Session", status_line: str = "") -> Optional[str]:
        """Send or edit footer message below output."""
        footer_text = self._build_footer_text(session, status_line=status_line)
        metadata = self._build_footer_metadata(session)

        existing_id = await self._get_footer_message_id(session)
        logger.trace(
            "[FOOTER] session=%s existing_id=%s footer_len=%d",
            session.session_id[:8],
            existing_id,
            len(footer_text),
        )
        if existing_id:
            success = await self.edit_message(session, existing_id, footer_text, metadata=metadata)
            if success:
                return existing_id
            # Edit failed (stale message) — clear tracked ID and skip.
            # Do NOT fall back to sending a new message here; the next
            # render cycle will create a fresh footer naturally.
            logger.debug(
                "[FOOTER] Edit failed for session=%s, clearing stale id %s", session.session_id[:8], existing_id
            )
            await self._clear_footer_message_id(session)
            return None

        new_id = await self.send_message(session, footer_text, metadata=metadata)
        logger.debug("[FOOTER] send_message returned %s for session=%s", new_id, session.session_id[:8])
        if new_id:
            await self._store_footer_message_id(session, new_id)
        return new_id

    def _build_footer_text(self, session: "Session", status_line: str = "") -> str:
        """Build footer text with session IDs first and status line last."""
        parts: list[str] = []
        session_lines = self._build_session_id_lines(session)
        if session_lines:
            parts.append(session_lines)
        if status_line:
            parts.append(status_line)
        return "\n".join(parts) if parts else "📋 session metadata unavailable"

    def format_output(self, tmux_output: str) -> str:
        """Format tmux output for the output message (no status line — that goes in the footer).

        Override in subclasses for platform-specific escaping.
        """
        if tmux_output:
            return f"```\n{tmux_output}\n```"
        return ""

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

    def _build_footer_metadata(self, _session: "Session") -> MessageMetadata:
        """Build platform-specific metadata for footer messages.

        Override in subclasses to add download buttons, etc.
        """
        return MessageMetadata()

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
        payload: dict[str, object],  # guard: loose-dict - Command payload for observers
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
        context: dict[str, object],  # guard: loose-dict - Voice event context
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
        - title: Direct title update (from summary) → rebuild display title
        - project_path/subdir: Path change → rebuild display title
        - active_agent/thinking_mode: Agent change → rebuild display title

        The database stores only the description; UI adapters construct the
        full display title (with agent/computer prefix) via get_display_title().

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

        # Rebuild display title when any title-affecting field changes
        title_affecting_fields = {
            SessionField.TITLE.value,
            SessionField.PROJECT_PATH.value,
            SessionField.SUBDIR.value,
            "active_agent",
            "thinking_mode",
        }

        if updated_fields.keys() & title_affecting_fields:
            display_title = await get_display_title_for_session(session)
            await self.client.update_channel_title(session, display_title)
            logger.info("Synced display title to UiAdapters for session %s: %s", session_id[:8], display_title)

        # Handle output summary updates (check both raw and summary fields).
        # Only dispatch output to the adapter whose key matches last_input_origin.
        # This prevents Telegram from receiving output when the user is interacting
        # via TUI/CLI/API/MCP — each adapter instance only sends output for sessions
        # that originated from IT.
        feedback_updated = (
            SessionField.LAST_OUTPUT_RAW.value in updated_fields or "last_output_summary" in updated_fields
        )
        if (
            feedback_updated
            and session.lifecycle_status != "headless"
            and session.last_input_origin == self.ADAPTER_KEY
        ):
            # Use helper to get appropriate feedback based on config
            feedback = get_last_output_summary(session) or ""
            if feedback:
                logger.debug(
                    "Feedback emit: session=%s origin=%s adapter=%s len=%d",
                    session_id[:8],
                    session.last_input_origin,
                    self.ADAPTER_KEY,
                    len(feedback),
                )
                await self.client.send_message(
                    session,
                    feedback,
                    metadata=MessageMetadata(parse_mode=None),
                    cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
                )
