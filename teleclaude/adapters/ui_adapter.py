"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output lane readiness
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop
from teleclaude.adapters.ui.output_delivery import OutputDeliveryMixin
from teleclaude.adapters.ui.threaded_output import ThreadedOutputMixin
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionStatusContext, TeleClaudeEvents, UiCommands
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.voice_message_handler import handle_voice

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


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

    # Platform API property name for the message ID (e.g. "id" for Discord/WhatsApp,
    # "message_id" for Telegram). Used when constructing platform API calls.
    OUTPUT_MESSAGE_ID_FIELD: str = "id"

    # Platform message size limit (subclasses can override)
    max_message_size: int = UI_MESSAGE_MAX_CHARS
    # Keep small Markdown entities (e.g. links) atomic across chunk boundaries.
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50
    # Markdown dialect used by this adapter for split-boundary marker tracking.
    # "markdownv2" — Telegram MarkdownV2 (state machine with escaping).
    # "gfm"        — GitHub-Flavoured Markdown (Discord, raw output).
    # "plain"      — no markdown tracking; word-boundary splits only.
    MARKDOWN_FLAVOR: str = "plain"

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

    async def ensure_output_lane_ready(
        self,
        session: Session,
        *,
        trigger: Literal["tmux_activity", "external_input", "daemon_startup", "repair"],
    ) -> Session:
        """Ensure this adapter's output lane is ready for the given trigger.

        UI adapters own output-lane readiness. The default implementation keeps
        tmux-activity wakeups effectively free and provisions channel state only
        for triggers that do not already prove lane viability.
        """
        if trigger == "tmux_activity":
            return session
        return await self.ensure_channel(session)

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
        """Get output message ID from this adapter's origin_metadata section."""
        fresh = await db.get_session(session.session_id)
        if fresh:
            session.origin_metadata = fresh.origin_metadata
        raw = self._origin_field(session, "output_message_id")
        result = str(raw) if raw else None
        logger.debug(
            "_get_output_message_id: adapter=%s session=%s raw=%s section_keys=%s",
            self.ADAPTER_KEY,
            session.session_id,
            raw,
            list(session.get_origin_section(self.ADAPTER_KEY).keys()),
        )
        return result

    async def _store_output_message_id(self, session: Session, message_id: str) -> None:
        """Store output message ID in this adapter's origin_metadata section."""
        await self._set_origin_field(session, output_message_id=message_id)
        logger.debug(
            "Stored output_message_id: adapter=%s session=%s message_id=%s",
            self.ADAPTER_KEY,
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
        if "output_message_id" in fields:
            logger.debug(
                "_set_origin_field WRITE: adapter=%s session=%s output_message_id=%s section_keys=%s",
                self.ADAPTER_KEY,
                session.session_id,
                fields.get("output_message_id"),
                list(section.keys()),
            )
        await db.update_origin_metadata(session.session_id, self.ADAPTER_KEY, section)
        # Keep in-memory session consistent for subsequent reads within the same request
        session.origin_metadata[self.ADAPTER_KEY] = section

    def _get_char_offset(self, session: Session) -> int:
        """Get adapter-specific char offset."""
        raw = self._origin_field(session, "char_offset", 0)
        return int(str(raw)) if raw is not None else 0

    async def _set_char_offset(self, session: Session, value: int) -> None:
        """Set adapter-specific char offset."""
        await self._set_origin_field(session, char_offset=value)

    def drop_pending_output(self, session_id: str) -> int:  # pylint: disable=unused-argument
        """Drop pending QoS output for a session. Override in subclasses with a QoS scheduler.

        Returns the number of dropped items (0 by default).
        """
        return 0

    async def clear_turn_state(self, session: Session) -> None:
        """Reset per-turn output state (char_offset only).

        Does NOT clear delivery timestamp — that persists in origin_metadata
        and prevents re-sending content that was already delivered.
        Does NOT clear output_message_id — cleared separately by
        break_threaded_turn or the cadence loop's turn break.
        """
        await self._set_char_offset(session, 0)

    async def force_output_pull(self, session: Session) -> None:
        """Trigger an immediate output pull for a session outside the cadence schedule."""
        if self._output_cadence is not None:
            await self._output_cadence.pull_session(session)

    async def _clear_output_message_id(self, session: Session) -> None:
        """Clear output message ID in this adapter's origin_metadata section."""
        await self._set_origin_field(session, output_message_id=None)
        logger.debug("Cleared output_message_id: adapter=%s session=%s", self.ADAPTER_KEY, session.session_id)

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
            return await self.send_message(
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

    async def _send_session_badge(self, session: Session) -> None:
        """Send session identification badge. Called once on session acceptance."""
        badge_text = self._build_session_id_lines(session)
        if badge_text:
            await self.send_message(session, badge_text, metadata=MessageMetadata(parse_mode=None))

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Handle lifecycle status transitions.

        Fires typing indicator and session badge on 'accepted', typing indicator
        on 'active' and 'active_output' to keep the indicator alive during long
        tool-use sequences.
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
                if context.status == "accepted":
                    try:
                        await self._send_session_badge(session)
                    except (OSError, RuntimeError, ValueError):
                        logger.debug(
                            "Session badge failed for session %s",
                            context.session_id,
                        )
            else:
                logger.debug(
                    "Typing skipped: session=%s found=%s lifecycle=%s",
                    context.session_id,
                    session is not None,
                    getattr(session, "lifecycle_status", None),
                )
