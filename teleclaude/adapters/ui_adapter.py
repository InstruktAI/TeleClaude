"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop
from teleclaude.adapters.ui.output_delivery import OutputDeliveryMixin
from teleclaude.adapters.ui.threaded_output import ThreadedOutputMixin
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionStatusContext, SessionUpdatedContext, TeleClaudeEvents, UiCommands
from teleclaude.core.models import (
    MessageMetadata,
    SessionField,
)
from teleclaude.core.session_utils import get_display_title_for_session, get_output_file
from teleclaude.core.voice_message_handler import handle_voice

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


@dataclass(frozen=True)
class _OutputUpdateRequest:
    """Normalized output-update payload routed through QoS."""

    session: Session
    output: str
    started_at: float
    last_output_changed_at: float
    is_final: bool = False
    exit_code: int | None = None
    render_markdown: bool = False


class UiAdapter(  # pyright: ignore[reportIncompatibleMethodOverride]  # type: ignore[misc]
    ThreadedOutputMixin, OutputDeliveryMixin, BaseAdapter
):
    """Base class for UI-enabled adapters.

    Provides output message management for platforms with editable messages.
    Subclasses can override max_message_size and add platform-specific formatting.
    """

    # Adapter key for metadata storage (subclasses MUST override)
    ADAPTER_KEY: str = "unknown"

    # Output cadence interval in seconds. Subclasses set this to their
    # platform's rate limit interval. 0 disables the cadence loop.
    OUTPUT_CADENCE_SECONDS: float = 0.0

    # Optional command handler overrides: command -> handler method name
    COMMAND_HANDLER_OVERRIDES: dict[str, str] = {}

    # Platform message size limit (subclasses can override)
    max_message_size: int = UI_MESSAGE_MAX_CHARS
    # Keep small Markdown entities (e.g. links) atomic across chunk boundaries.
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50

    # Per-session lock to serialize output delivery and prevent concurrent
    # lanes from racing on output_message_id reads/writes.
    _output_delivery_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def _get_output_delivery_lock(cls, session_id: str) -> asyncio.Lock:
        """Get/create the per-session output lock."""
        lock = cls._output_delivery_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._output_delivery_locks[session_id] = lock
        return lock

    def __init__(self, client: AdapterClient) -> None:
        """Initialize UiAdapter and register event listeners.

        Args:
            client: AdapterClient instance
        """
        # Set client (BaseAdapter has no __init__, just requires this attribute)
        self.client = client

        # Output cadence loop — pulls transcripts and renders on adapter's own schedule.
        self._output_cadence: OutputCadenceLoop | None = None
        if self.OUTPUT_CADENCE_SECONDS > 0:
            self._output_cadence = OutputCadenceLoop(self, self.OUTPUT_CADENCE_SECONDS)

        # Register event listeners
        event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STATUS, self._handle_session_status)

    def start_output_cadence(self) -> None:
        """Start the output cadence loop (call after adapter.start())."""
        if self._output_cadence is not None:
            self._output_cadence.start()

    async def stop_output_cadence(self) -> None:
        """Stop the output cadence loop (call before adapter.stop())."""
        if self._output_cadence is not None:
            await self._output_cadence.stop()

    # === Adapter Metadata Helpers ===

    async def cleanup_stale_resources(self) -> int:
        """Clean up adapter-specific stale resources. Returns count of cleaned items."""
        return 0

    async def ensure_channel(self, session: Session) -> Session:
        """Ensure adapter-specific channel exists (default no-op)."""
        return session

    async def recover_lane_error(
        self,
        session: Session,
        error: Exception,
        task_factory: Callable[[UiAdapter, Session], Awaitable[object]],
        display_title: str,
    ) -> object | None:
        """Attempt platform-specific recovery from a lane task error.

        Returns the task result if recovery succeeded, or None on recovery failure.
        Default: re-raises (no recovery available).
        """
        raise error

    async def _get_output_message_id(self, session: Session) -> str | None:
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

    async def _store_output_message_id(self, session: Session, message_id: str) -> None:
        """Store output_message_id in dedicated DB column.

        Uses atomic column write (not adapter_metadata blob) to prevent
        concurrent adapter_metadata writes from clobbering the value.
        """
        await db.set_output_message_id(session.session_id, message_id)
        session.output_message_id = message_id  # Keep in-memory session consistent
        logger.debug(
            "Stored output_message_id: session=%s message_id=%s",
            session.session_id,
            message_id,
        )

    def _origin_field(self, session: Session, field: str, default: object = None) -> object:
        """Read a field from this adapter's origin_metadata section."""
        return session.get_origin_section(self.ADAPTER_KEY).get(field, default)

    async def _set_origin_field(self, session: Session, **fields: object) -> None:
        """Write fields to this adapter's origin_metadata section (merge-write)."""
        section = session.get_origin_section(self.ADAPTER_KEY)
        section.update(fields)
        await db.update_origin_metadata(session.session_id, self.ADAPTER_KEY, section)
        # Keep in-memory session consistent for subsequent reads within the same request
        session.origin_metadata[self.ADAPTER_KEY] = section

    async def _get_footer_message_id(self, session: Session) -> str | None:
        """Get threaded footer message id from adapter namespace."""
        val = self._origin_field(session, "footer_message_id")
        return str(val) if val else None

    async def _store_footer_message_id(self, session: Session, message_id: str) -> None:
        """Store threaded footer message id in adapter namespace."""
        await self._set_origin_field(session, footer_message_id=message_id)
        logger.debug(
            "Stored footer_message_id: session=%s message_id=%s",
            session.session_id,
            message_id,
        )

    async def _clear_footer_message_id(self, session: Session) -> None:
        """Clear threaded footer message id from adapter namespace."""
        await self._set_origin_field(session, footer_message_id=None)
        logger.debug("Cleared footer_message_id: session=%s", session.session_id)

    async def _get_badge_sent(self, session: Session) -> bool:
        """Check if session badge has been sent."""
        fresh = await db.get_session(session.session_id)
        if fresh:
            session.origin_metadata = fresh.origin_metadata
        return bool(self._origin_field(session, "badge_sent", False))

    async def _set_badge_sent(self, session: Session, value: bool) -> None:
        """Update session badge sent status."""
        await self._set_origin_field(session, badge_sent=value)

    def _get_char_offset(self, session: Session) -> int:
        """Get adapter-specific char offset."""
        raw = self._origin_field(session, "char_offset", 0)
        return int(str(raw)) if raw is not None else 0

    async def _set_char_offset(self, session: Session, value: int) -> None:
        """Set adapter-specific char offset."""
        await self._set_origin_field(session, char_offset=value)

    async def _cleanup_footer_if_present(self, session: Session) -> None:
        """Delete and clear any tracked threaded footer message."""
        previous_footer_id = await self._get_footer_message_id(session)
        if not previous_footer_id:
            return
        try:
            await self.delete_message(session, previous_footer_id)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug(
                "Best-effort stale threaded footer delete failed: session=%s message_id=%s err=%s",
                session.session_id,
                previous_footer_id,
                exc,
            )
        finally:
            await self._clear_footer_message_id(session)

    def drop_pending_output(self, session_id: str) -> int:  # pylint: disable=unused-argument
        """Drop pending QoS output for a session. Override in subclasses with a QoS scheduler.

        Returns the number of dropped items (0 by default).
        """
        return 0

    async def move_badge_to_bottom(self, session: Session) -> None:
        """Move the session badge to the absolute bottom of the thread."""
        await self._cleanup_footer_if_present(session)
        await self._send_footer(session)

    async def clear_turn_state(self, session: Session) -> None:
        """Reset per-turn output state (output_message_id, char_offset, cadence digest)."""
        if self._output_cadence is not None:
            self._output_cadence.clear_session(session.session_id)
        await self._clear_output_message_id(session)
        await self._set_char_offset(session, 0)

    async def force_output_pull(self, session: Session) -> None:
        """Trigger an immediate output pull for a session outside the cadence schedule."""
        if self._output_cadence is not None:
            await self._output_cadence.pull_session(session)

    async def _send_output_update_via_qos(
        self,
        scheduler: OutputQoSScheduler,
        request: _OutputUpdateRequest,
    ) -> str | None:
        """Send immediately or enqueue an output update through the QoS scheduler."""
        if scheduler._policy.mode == "off":  # pylint: disable=protected-access
            return await UiAdapter.send_output_update(
                self,
                request.session,
                request.output,
                request.started_at,
                request.last_output_changed_at,
                request.is_final,
                request.exit_code,
                request.render_markdown,
            )

        async def _dispatch() -> str | None:
            return await UiAdapter.send_output_update(
                self,
                request.session,
                request.output,
                request.started_at,
                request.last_output_changed_at,
                request.is_final,
                request.exit_code,
                request.render_markdown,
            )

        scheduler.enqueue(request.session.session_id, _dispatch, is_final=request.is_final)
        return None

    async def _clear_output_message_id(self, session: Session) -> None:
        """Clear output_message_id in dedicated DB column.

        Uses atomic column write (not adapter_metadata blob) to prevent
        concurrent adapter_metadata writes from clobbering the value.
        """
        await db.set_output_message_id(session.session_id, None)
        session.output_message_id = None  # Keep in-memory session consistent
        logger.debug(
            "Cleared output_message_id: session=%s",
            session.session_id,
        )

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

    def _build_session_id_lines(self, session: Session) -> str:
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

    async def _pre_handle_user_input(self, _session: Session) -> None:
        """Called before handling user input - cleanup ephemeral messages.

        All tracked messages (feedback, user input) cleaned here.
        """
        # User input messages (pending_deletions) cleaned via event handler, not here

    async def send_typing_indicator(self, session: Session) -> None:
        """Send platform-specific typing indicator.

        Override in subclasses to implement platform typing API.
        Default implementation is a no-op.

        Args:
            session: Session object
        """
        # No-op default implementation

    async def _dispatch_command(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: Session,
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: dict[str, object],  # guard: loose-dict - Command payload for UI adapters
        handler: Callable[[], Awaitable[object]],
    ) -> object:
        """Run command with UI pre/post handling and broadcast to other adapters."""
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
                    last_message_sent_at=datetime.now(UTC).isoformat(),
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

        async def _send_notice(sid: str, message: str, metadata: MessageMetadata) -> str | None:
            session = await db.get_session(sid)
            if not session:
                logger.warning("Session %s not found for message", sid)
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
            context=context,
            send_message=_send_notice,
            delete_message=self._delete_message_by_session_id,
        )

    async def _delete_message_by_session_id(self, sid: str, message_id: str) -> None:
        session = await db.get_session(sid)
        if not session:
            logger.warning("Session %s not found for delete", sid)
            return
        await self.delete_message(session, message_id)

    # ==================== File Handling ====================

    async def get_session_file(
        self,
        _session_id: str,
    ) -> str | None:
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

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Handle lifecycle status transitions.

        Fires typing indicator on 'accepted' (prompt received), 'active'
        (session confirmed), and 'active_output' (tool use observed) to keep
        the indicator alive during long tool-use sequences.
        Platform adapters override for additional decoration (footer, badges).
        """
        if context.status in ("active", "accepted", "active_output"):
            session = await db.get_session(context.session_id)
            if session and session.lifecycle_status != "headless":
                logger.debug(
                    "Typing trigger: session=%s status=%s adapter=%s",
                    context.session_id,
                    context.status,
                    self.ADAPTER_KEY,
                )
                try:
                    await self.send_typing_indicator(session)
                except (OSError, RuntimeError, ValueError):
                    logger.debug(
                        "Typing indicator failed for session %s on status %s",
                        context.session_id,
                        context.status,
                    )
            else:
                logger.debug(
                    "Typing skipped: session=%s found=%s lifecycle=%s",
                    context.session_id,
                    session is not None,
                    getattr(session, "lifecycle_status", None),
                )

    @staticmethod
    def _format_lifecycle_status(status: str) -> str:
        """Format a lifecycle status string for platform display."""
        emoji: dict[str, str] = {
            "accepted": "⏱",
            "active": "💬",
            "active_output": "🔄",
            "completed": "✅",
            "error": "❌",
            "closed": "🔒",
        }
        icon = emoji.get(status, "❓")
        return f"{icon} {status.replace('_', ' ')}"

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
            logger.info("Synced display title to UiAdapters for session %s: %s", session_id, display_title)
