"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output lane readiness
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.qos.action_throttler import AdapterActionThrottler
from teleclaude.adapters.ui.delivery_mixin import OutputDeliveryMixin
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.events import UiCommands
from teleclaude.core.models import MessageMetadata
from teleclaude.core.voice_message_handler import handle_voice
from teleclaude.utils.transcript import extract_last_turn_boundary_timestamp
from teleclaude.utils.transcript._utils import _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class UiAdapter(  # pyright: ignore[reportIncompatibleMethodOverride]  # type: ignore[misc]
    OutputDeliveryMixin,
    BaseAdapter,
):
    """Base class for UI-enabled adapters.

    Provides output message management for platforms with editable messages.
    Subclasses can override max_message_size and add platform-specific formatting.
    """

    # Adapter key for metadata storage (subclasses MUST override)
    ADAPTER_KEY: str = "unknown"

    # Optional command handler overrides: command -> handler method name
    COMMAND_HANDLER_OVERRIDES: dict[str, str] = {}

    # Platform API property name for the message ID (e.g. "id" for Discord/WhatsApp,
    # "message_id" for Telegram). Used when constructing platform API calls.
    OUTPUT_MESSAGE_ID_FIELD: str = "id"

    # Platform message size limit (subclasses can override)
    max_message_size: int = UI_MESSAGE_MAX_CHARS
    # Keep small Markdown entities (e.g. links) atomic across chunk boundaries.
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS = 50

    def __init__(self, client: AdapterClient) -> None:
        """Initialize UiAdapter and register event listeners.

        Args:
            client: AdapterClient instance
        """
        # Set client (BaseAdapter has no __init__, just requires this attribute)
        self.client = client
        self._action_throttler = AdapterActionThrottler()

    # === Adapter Metadata Helpers ===

    async def cleanup_stale_resources(self) -> int:
        """Clean up adapter-specific stale resources. Returns count of cleaned items."""
        return 0

    def headless_prefix(self, session: Session) -> str:
        """Universal user-facing marker for headless sessions.

        Prepended by every UI adapter's display formatter so customers and
        admins can see at a glance that a session is unattended and may be
        adoptable. Defined once on the base so the marker string and the
        condition stay consistent across all adapters and future surfaces.
        """
        return "[HEADLESS] " if session.lifecycle_status == "headless" else ""

    def title_body(self, session: Session) -> str:
        """Platform-specific decoration over the canonical semantic title.

        Default: bare semantic title with an "Untitled" fallback. Subclasses
        override only when their platform needs additional disambiguation
        (e.g. Discord catch-all forum prepending project name).
        """
        return session.title or "Untitled"

    def display_title(self, session: Session) -> str:
        """Full user-facing title used to set this adapter's renamable surface."""
        return f"{self.headless_prefix(session)}{self.title_body(session)}"

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

    def get_last_delivered_at(self, session: Session) -> datetime | None:
        """Read last_delivered_at from this adapter's origin_metadata section."""
        raw = self._origin_field(session, "last_delivered_at")
        if isinstance(raw, str):
            return _parse_timestamp(raw)
        return None

    async def set_last_delivered_at(self, session: Session, ts: datetime) -> None:
        """Write last_delivered_at to this adapter's origin_metadata section."""
        await self._set_origin_field(session, last_delivered_at=ts.isoformat())

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
        cast(Any, session.origin_metadata)[self.ADAPTER_KEY] = section

    def _get_char_offset(self, session: Session) -> int:
        """Get adapter-specific char offset."""
        raw = self._origin_field(session, "char_offset", 0)
        return int(str(raw)) if raw is not None else 0

    async def _set_char_offset(self, session: Session, value: int) -> None:
        """Set adapter-specific char offset."""
        await self._set_origin_field(session, char_offset=value)

    def drop_pending_output(self, session_id: str) -> int:
        """Drop pending QoS output for a session. Override in subclasses with a QoS scheduler.

        Returns the number of dropped items (0 by default).
        """
        return 0

    async def _write_cleared_turn_state(self, session: Session, **extra_fields: object) -> None:
        await self._set_origin_field(
            session,
            char_offset=0,
            output_message_id=None,
            last_delivered_at=datetime.now(UTC).isoformat(),
            **extra_fields,
        )

    async def clear_turn_state(self, session: Session) -> None:
        """Reset threaded delivery receipts so the next render sends fresh."""
        await self._write_cleared_turn_state(session)

    async def open_input_turn(self, session: Session) -> None:
        await self._write_cleared_turn_state(session, turn_open_pending=True)

    async def _maybe_clear_on_turn_boundary(self, session: Session) -> None:
        """Reset per-adapter delivery state when a new turn has started.

        Compares the transcript's latest genuine user message timestamp to the
        anchor persisted in origin_metadata. When it advances, the previous
        turn's tracking message must not be edited with new-turn content — it
        would overwrite displayed output and, on overflow, silently bury
        chunk 1 inside a stale message that has already scrolled away.
        """
        transcript_path = session.native_log_file
        active_agent = session.active_agent
        if not transcript_path or not active_agent:
            return
        try:
            agent_name = AgentName.from_str(active_agent)
        except ValueError:
            return

        latest_user_ts = extract_last_turn_boundary_timestamp(transcript_path, agent_name)
        if latest_user_ts is None:
            return

        stored_raw = self._origin_field(session, "turn_anchor_ts")
        stored_ts = _parse_timestamp(stored_raw) if isinstance(stored_raw, str) else None
        turn_open_pending = self._origin_field(session, "turn_open_pending") is True

        if stored_ts is None:
            pending_update = {"turn_open_pending": None} if turn_open_pending else {}
            await self._set_origin_field(session, turn_anchor_ts=latest_user_ts.isoformat(), **pending_update)
            return

        if turn_open_pending:
            if latest_user_ts > stored_ts:
                await self._set_origin_field(
                    session,
                    turn_anchor_ts=latest_user_ts.isoformat(),
                    turn_open_pending=None,
                )
            return

        if latest_user_ts <= stored_ts:
            return

        # New turn: clear delivery state so the next render creates a fresh message.
        await self.clear_turn_state(session)
        await self._set_origin_field(session, turn_anchor_ts=latest_user_ts.isoformat())
        logger.debug(
            "Turn boundary detected: adapter=%s session=%s previous_anchor=%s new_anchor=%s",
            self.ADAPTER_KEY,
            session.session_id,
            stored_ts.isoformat(),
            latest_user_ts.isoformat(),
        )

    async def send_output_update(
        self,
        session: Session,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: int | None = None,
        render_markdown: bool = False,
        multi_message: bool = False,
        delivery_ts: datetime | None = None,
    ) -> str | None:
        """Handle live output pushed by the daemon-owned coordinator."""
        _ = (started_at, last_output_changed_at, is_final, exit_code, render_markdown)
        await self._maybe_clear_on_turn_boundary(session)
        return await self.send_threaded_output(session, output, multi_message=multi_message, delivery_ts=delivery_ts)

    async def _clear_output_message_id(self, session: Session) -> None:
        """Clear output message ID in this adapter's origin_metadata section."""
        await self._set_origin_field(session, output_message_id=None)
        logger.debug("Cleared output_message_id: adapter=%s session=%s", self.ADAPTER_KEY, session.session_id)

    # === Command Registration ===

    def _get_command_handlers(self) -> list[tuple[str, object]]:
        """Get command handlers by convention: command_name -> _handle_{command_name}.

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
            lines.append(f"\U0001f4cb tc: {session.session_id}")

        # Native agent session ID (from session - set when any agent starts)
        if session.native_session_id:
            agent_name = session.active_agent or "ai"
            lines.append(f"\U0001f916 {agent_name}: {session.native_session_id}")

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

    def get_action_throttle_interval_s(self, action_kind: str) -> float:
        """Return the minimum interval between adapter control actions."""
        if action_kind == "typing":
            return 5.0
        return 0.0

    def _action_throttle_key(self, session: Session, action_kind: str) -> str:
        """Build the adapter-local throttle key for an outbound action."""
        return f"{self.ADAPTER_KEY}:{session.session_id}:{action_kind}"

    async def _run_throttled_action(
        self,
        session: Session,
        action_kind: str,
        action: Callable[[], Awaitable[object]],
    ) -> object | None:
        """Run an adapter action only when outside the configured throttle window."""
        now = time.monotonic()
        interval = self.get_action_throttle_interval_s(action_kind)
        throttle_key = self._action_throttle_key(session, action_kind)
        if not self._action_throttler.allow(throttle_key, min_interval_s=interval, now=now):
            logger.debug(
                "Adapter action throttled: adapter=%s session=%s action=%s interval_s=%.3f",
                self.ADAPTER_KEY,
                session.session_id,
                action_kind,
                interval,
            )
            return None
        return await action()

    async def _dispatch_command(
        self,
        session: Session,
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: dict[str, object],  # guard: loose-dict - Command payload for UI adapters
        handler: Callable[[], Awaitable[object]],
    ) -> object:
        """Run command with UI pre/post handling and broadcast to other adapters."""
        if message_id:
            await self.client.pre_handle_command(session, metadata.origin)

        result = await handler()

        if message_id:
            await self.client.post_handle_command(session, message_id, metadata.origin)

        return result

    async def dispatch_command(
        self,
        session: Session,
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: dict[str, object],  # guard: loose-dict - Command payload for UI adapters
        handler: Callable[[], Awaitable[object]],
    ) -> object:
        """Public entry point for command dispatch from outside the adapter (e.g. inbound hooks)."""
        return await self._dispatch_command(session, message_id, metadata, command_name, payload, handler)

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
            destination = resolve_destination(session, self.ADAPTER_KEY, metadata=metadata)
            return await self.send_message(
                destination,
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
        destination = resolve_destination(session, self.ADAPTER_KEY)
        await self.delete_message(destination, message_id)

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

        """
        return None  # Default: no download functionality

    # ==================== Event Handlers ====================

    async def _send_session_badge(self, session: Session) -> None:
        """Send session identification badge. Called once on session acceptance."""
        badge_text = self._build_session_id_lines(session)
        if badge_text:
            badge_metadata = MessageMetadata(parse_mode=None)
            destination = resolve_destination(session, self.ADAPTER_KEY, metadata=badge_metadata)
            await self.send_message(destination, badge_text, metadata=badge_metadata)

    async def on_session_status(self, session: Session, status: str) -> None:
        """React to a lifecycle status transition for this adapter's session.

        Dispatched by ``AdapterClient.dispatch_session_status`` after origin
        resolution — only the responsible adapter is invoked. The adapter owns
        its own status-filter policy: typing fires on ``active`` / ``accepted`` /
        ``active_output`` for non-headless sessions; badge fires only on
        ``accepted``.
        """
        if not self._presence_eligible(session, status):
            return
        await self._update_typing_presence(session, status)
        if status == "accepted":
            await self._trigger_session_badge(session)

    def _presence_eligible(self, session: Session, status: str) -> bool:
        """Gate shared by typing and badge: known status, non-headless session."""
        if status not in ("active", "accepted", "active_output"):
            return False
        if session.lifecycle_status == "headless":
            logger.debug(
                "Typing skipped (headless): session=%s adapter=%s",
                session.session_id,
                self.ADAPTER_KEY,
            )
            return False
        return True

    async def _update_typing_presence(self, session: Session, status: str) -> None:
        """Presence-only concern: fire the throttled typing indicator."""
        logger.debug(
            "Typing trigger: session=%s status=%s adapter=%s",
            session.session_id,
            status,
            self.ADAPTER_KEY,
        )
        try:
            await self._run_throttled_action(
                session,
                "typing",
                lambda: self.send_typing_indicator(session),
            )
        except (OSError, RuntimeError, ValueError):
            logger.debug(
                "Typing indicator failed for session %s on status %s",
                session.session_id,
                status,
            )

    async def _trigger_session_badge(self, session: Session) -> None:
        """Session-identification concern: fire the once-on-acceptance badge."""
        try:
            await self._run_throttled_action(
                session,
                "session_badge",
                lambda: self._send_session_badge(session),
            )
        except (OSError, RuntimeError, ValueError):
            logger.debug(
                "Session badge failed for session %s",
                session.session_id,
            )

    async def on_session_updated(self, session: Session, updated_fields: Mapping[str, object]) -> None:
        """React to a session-field update for this adapter's session.

        Default no-op. Subclasses override when they have UI state that
        depends on session metadata (e.g. Discord thread-topper).
        """
        _ = session, updated_fields
