"""Base adapter for UI-enabled platforms (Telegram, Slack, WhatsApp).

UI adapters provide:
- Output lane readiness
- Output message management (edit/create messages)
- Feedback message cleanup
- Message formatting and display
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.qos.action_throttler import AdapterActionThrottler
from teleclaude.adapters.ui.output_delivery import _delivery_options_from_kwargs
from teleclaude.adapters.ui.threaded_output import OverflowContext, OverflowPlan, ThreadDelivery
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionStatusContext, TeleClaudeEvents, UiCommands
from teleclaude.core.models import MessageMetadata
from teleclaude.core.voice_message_handler import handle_voice
from teleclaude.utils.transcript import extract_last_turn_boundary_timestamp
from teleclaude.utils.transcript._utils import _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class UiAdapter(  # pyright: ignore[reportIncompatibleMethodOverride]  # type: ignore[misc]
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

    # -------------------------------------------------------------------------
    # Markdown strategy — plain-text defaults (override per adapter)
    # -------------------------------------------------------------------------

    def _markdown_initial_state(self) -> Any:
        """Return the zero-state for this adapter's markdown parser."""
        return None

    def _continuation_prefix_for_state(self, state: Any) -> str:
        """Return opening markers to continue a previously closed chunk."""
        _ = state
        return ""

    def _truncate_for_overflow(self, body_text: str, max_chars: int) -> tuple[str, int]:
        """Truncate *body_text* to *max_chars*.

        Returns (chunk, consumed_display).
        Default: word-boundary split with no marker tracking.
        """
        candidate = body_text[:max_chars]
        last_space = candidate.rfind(" ")
        split_idx = last_space if last_space > (len(candidate) * 0.8) else max_chars
        return body_text[:split_idx], split_idx

    def _scan_markdown_state(self, consumed: str, state: Any) -> Any:
        """Return the parser state after consuming *consumed* from *state*."""
        _ = consumed
        return state

    def _finalize_overflow_split(
        self,
        active_text: str,
        overflow_context: OverflowContext,
        split_idx: int,
        chunk: str,
    ) -> tuple[int, str]:
        """Optional post-processing after the split point is computed."""
        _ = (active_text, overflow_context)
        return split_idx, chunk

    def _balance_intermediate_chunk(self, text: str) -> str:
        """Close any open markers for a live intermediate render."""
        return text

    # -------------------------------------------------------------------------
    # Threaded output delivery (was ThreadedOutputMixin)
    # -------------------------------------------------------------------------

    async def sync_threaded_session_state(self, session: Session) -> None:
        """Public wrapper for refreshing the mutable session output state."""
        await self._sync_threaded_session_state(session)

    async def send_threaded_output(
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
        *,
        delivery_ts: datetime | None = None,
    ) -> str | None:
        """Send or edit threaded output message with smart pagination."""
        lock = self._get_output_delivery_lock(session.session_id)
        async with lock:
            await self._sync_threaded_session_state(session)

            converted_text = self._convert_markdown_for_platform(text)
            logger.debug(
                "[THREADED] Rendering: adapter=%s session=%s text_len=%d converted_len=%d",
                self.ADAPTER_KEY,
                session.session_id,
                len(text),
                len(converted_text),
            )
            result = await self._send_threaded_output_unlocked(
                session,
                converted_text,
                multi_message=multi_message,
            )
            if result and delivery_ts is not None:
                await self.set_last_delivered_at(session, delivery_ts)
            logger.debug(
                "[THREADED] Result: adapter=%s session=%s result=%s",
                self.ADAPTER_KEY,
                session.session_id,
                type(result).__name__ if result else "None",
            )
            return result

    async def _send_threaded_output_unlocked(
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
    ) -> str | None:
        """Threaded-output core logic. Caller must hold the session output lock."""
        # 1. Get current offset and ID.
        char_offset = await self._normalize_char_offset(session, text)
        output_message_id = await self._get_output_message_id(session)
        logger.debug(
            "[THREADED_UNLOCKED] adapter=%s session=%s char_offset=%d text_len=%d output_message_id=%s",
            self.ADAPTER_KEY,
            session.session_id,
            char_offset,
            len(text),
            output_message_id,
        )

        # 2. Slice text to get the "active" portion.
        active_text = text[char_offset:]
        if not active_text and output_message_id:
            return output_message_id

        # 3. Re-derive markdown state at the resume point. The cumulative text +
        #    char_offset are the source of truth: whatever markers are open at
        #    position char_offset can be re-derived by scanning text[:char_offset]
        #    every render. This guarantees that on every edit of a post-seal
        #    chunk, the reopen prefix (e.g. ```\n for an open code fence) is
        #    reapplied — even across separate top-level renders where any
        #    in-memory parameter would have been lost.
        continuation_state = self._scan_markdown_state(text[:char_offset], self._markdown_initial_state())
        continuation_prefix = self._continuation_prefix_for_state(continuation_state)
        display_text = f"{continuation_prefix}{active_text}"

        # 4. Check for overflow.
        limit = self.max_message_size - 10
        if len(display_text) > limit:
            overflow_context = OverflowContext(
                continuation_prefix=continuation_prefix,
                available_for_content=max(limit, 1),
            )
            overflow_plan = self._plan_overflow(active_text, overflow_context)
            await self._seal_thread_chunk(
                session,
                output_message_id,
                overflow_plan.chunk,
                multi_message=multi_message,
            )
            await self._set_char_offset(session, char_offset + overflow_plan.split_idx)
            await self._clear_output_message_id(session)

            # Recurse: the new char_offset will re-derive continuation state
            # from text[:new_char_offset] on the next iteration.
            return await self._send_threaded_output_unlocked(
                session,
                text,
                multi_message=multi_message,
            )

        # --- NORMAL CASE: FIT AND SEND ---
        return await self._deliver_thread_body(
            session,
            display_text,
            ThreadDelivery(
                output_message_id=output_message_id,
                multi_message=multi_message,
            ),
        )

    async def _sync_threaded_session_state(self, session: Session) -> None:
        """Refresh mutable session output state from the database before rendering."""
        fresh = await db.get_session(session.session_id)
        if fresh:
            session.origin_metadata = fresh.origin_metadata
            session.last_output_digest = fresh.last_output_digest

    async def _normalize_char_offset(self, session: Session, text: str) -> int:
        """Reset an invalid char offset and return the effective offset."""
        char_offset = self._get_char_offset(session)
        if len(text) < char_offset:
            await self._set_char_offset(session, 0)
            return 0
        return char_offset

    def _plan_overflow(
        self,
        active_text: str,
        overflow_context: OverflowContext,
    ) -> OverflowPlan:
        """Compute the next sealed chunk when the display body overflows."""
        body_text = f"{overflow_context.continuation_prefix}{active_text}"
        chunk, consumed_display = self._truncate_for_overflow(body_text, overflow_context.available_for_content)

        consumed_prefix = min(consumed_display, len(overflow_context.continuation_prefix))
        split_idx = consumed_display - consumed_prefix

        split_idx, chunk = self._finalize_overflow_split(active_text, overflow_context, split_idx, chunk)

        # Ensure we always make progress (avoid infinite split at position 0).
        if split_idx <= 0 and active_text:
            split_idx = min(len(active_text), overflow_context.available_for_content)
            chunk, _ = self._truncate_for_overflow(
                f"{overflow_context.continuation_prefix}{active_text[:split_idx]}",
                overflow_context.available_for_content,
            )

        return OverflowPlan(chunk=chunk, split_idx=split_idx)

    async def _seal_thread_chunk(
        self,
        session: Session,
        output_message_id: str | None,
        sealed_text: str,
        *,
        multi_message: bool,
    ) -> None:
        """Commit a sealed overflow chunk before continuing with the remainder."""
        seal_metadata = self._build_metadata_for_thread()
        if output_message_id:
            await self._try_edit_output_message(session, sealed_text, seal_metadata)
            return

        new_id = await self.send_message(
            session,
            sealed_text,
            metadata=seal_metadata,
            multi_message=multi_message,
        )
        if new_id:
            await self._store_output_message_id(session, new_id)

    async def _deliver_thread_body(
        self,
        session: Session,
        display_text: str,
        delivery: ThreadDelivery,
    ) -> str | None:
        """Deliver the current threaded body without digest-based dedupe."""
        if display_text:
            display_text = self._balance_intermediate_chunk(display_text)
            if not display_text:
                return delivery.output_message_id

        metadata = self._build_metadata_for_thread()
        return await self._deliver_output_unlocked(
            session,
            display_text,
            metadata,
            multi_message=delivery.multi_message,
            dedupe_by_digest=False,
        )

    # -------------------------------------------------------------------------
    # Output delivery (was OutputDeliveryMixin)
    # -------------------------------------------------------------------------

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Build metadata for threaded content messages. Override for platform-specific parse mode."""
        return MessageMetadata()

    async def _deliver_output(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        **delivery_kwargs: object,
    ) -> str | None:
        """Unified output delivery: dedup, edit/send."""
        options = _delivery_options_from_kwargs(delivery_kwargs)
        lock = self._get_output_delivery_lock(session.session_id)
        async with lock:
            return await self._deliver_output_unlocked(session, text, metadata, options=options)

    async def _deliver_output_unlocked(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        **delivery_kwargs: object,
    ) -> str | None:
        """Core output delivery logic. Caller must hold the session output lock."""
        options = _delivery_options_from_kwargs(delivery_kwargs)
        display_digest = sha256(text.encode("utf-8")).hexdigest()

        # Digest short-circuit is kept for non-threaded output updates.
        # Threaded mode uses cadence-loop-driven rendering; digest dedupe is not applicable.
        if options.dedupe_by_digest and session.last_output_digest == display_digest:
            return await self._get_output_message_id(session)

        # 2. Try edit existing
        edited = await self._try_edit_output_message(session, text, metadata)
        if edited:
            logger.debug("[DELIVER] Edited existing: adapter=%s session=%s", self.ADAPTER_KEY, session.session_id)
            await db.update_session(session.session_id, last_output_digest=display_digest)
            return await self._get_output_message_id(session)

        # 3. Edit failed -> send new
        logger.debug(
            "[DELIVER] Edit failed, sending new: adapter=%s session=%s text_len=%d",
            self.ADAPTER_KEY,
            session.session_id,
            len(text),
        )
        new_id = await self.send_message(
            session,
            text,
            metadata=metadata,
            multi_message=options.multi_message,
        )
        logger.debug(
            "[DELIVER] New message result: adapter=%s session=%s new_id=%s",
            self.ADAPTER_KEY,
            session.session_id,
            new_id,
        )
        if new_id:
            await self._store_output_message_id(session, new_id)
            await db.update_session(session.session_id, last_output_digest=display_digest)
        return new_id

    async def _try_edit_output_message(self, session: Session, text: str, metadata: MessageMetadata) -> bool:
        """Try to edit existing output message, clear message_id if edit fails.

        Returns:
            True if edited successfully, False if no message_id or edit failed
        """
        message_id = await self._get_output_message_id(session)
        logger.debug(
            "[TRY_EDIT] session=%s existing_message_id=%s",
            session.session_id,
            message_id if message_id else "None",
        )
        if not message_id:
            logger.debug("[TRY_EDIT] No existing message_id, will send new message")
            return False

        logger.debug("[TRY_EDIT] Attempting to edit message %s for session %s", message_id, session.session_id)
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
                await self.send_message(
                    session,
                    f"\u274c {error_message}",
                    metadata=self._metadata(),
                )
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            logger.error("Failed to send error feedback for session %s: %s", session_id, error)

    # -------------------------------------------------------------------------

    def __init__(self, client: AdapterClient) -> None:
        """Initialize UiAdapter and register event listeners.

        Args:
            client: AdapterClient instance
        """
        # Set client (BaseAdapter has no __init__, just requires this attribute)
        self.client = client
        self._action_throttler = AdapterActionThrottler()

        event_bus.subscribe(TeleClaudeEvents.SESSION_STATUS, self._handle_session_status)

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
        session.origin_metadata[self.ADAPTER_KEY] = section

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

    async def clear_turn_state(self, session: Session) -> None:
        """Reset char_offset, clear output_message_id, and seal last_delivered_at.

        Called from send_output_update when a new-turn boundary is detected so
        the next delivery starts a fresh tracking message instead of editing a
        stale one from the previous turn.
        """
        await self._set_char_offset(session, 0)
        await self._set_origin_field(
            session,
            output_message_id=None,
            last_delivered_at=datetime.now(UTC).isoformat(),
        )
        logger.debug("Turn state cleared: adapter=%s session=%s", self.ADAPTER_KEY, session.session_id)

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

        if stored_ts is None:
            # First delivery on this adapter — record the anchor without clearing.
            await self._set_origin_field(session, turn_anchor_ts=latest_user_ts.isoformat())
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

        """
        return None  # Default: no download functionality

    # ==================== Event Handlers ====================

    async def _send_session_badge(self, session: Session) -> None:
        """Send session identification badge. Called once on session acceptance."""
        badge_text = self._build_session_id_lines(session)
        if badge_text:
            await self.send_message(session, badge_text, metadata=MessageMetadata(parse_mode=None))

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Handle lifecycle status transitions.

        Fires throttled typing on 'accepted' and 'active'. Session badges are
        emitted once on 'accepted'. 'active_output' is observer-only and does
        not trigger direct adapter API calls.
        """
        if context.status in ("active", "accepted"):
            session = await db.get_session(context.session_id)
            if session and session.lifecycle_status != "headless":
                logger.debug(
                    "Typing trigger: session=%s status=%s adapter=%s",
                    context.session_id,
                    context.status,
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
                        context.session_id,
                        context.status,
                    )
                if context.status == "accepted":
                    try:
                        await self._run_throttled_action(
                            session,
                            "session_badge",
                            lambda: self._send_session_badge(session),
                        )
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
