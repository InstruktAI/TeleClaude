"""Base adapter for UI-enabled platforms.

UI adapters provide:
- Output lane readiness
- Send-once output: each finished turn is sent once, overflowing into
  continuation messages when it exceeds the platform's message size
- Feedback message cleanup
- Message formatting and display

Platforms whose messages can be edited in place extend ``EditableUiAdapter``
to stream live output instead.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.qos.action_throttler import AdapterActionThrottler
from teleclaude.adapters.ui.message_delivery import MessageDeliveryMixin
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.db import db
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.inbound_errors import SessionMessageRejectedError, SessionMessageRejectionReason
from teleclaude.core.message_lifetime import retains_human_conversation_input
from teleclaude.core.models import ContentFormat, MessageMetadata
from teleclaude.core.models._types import JsonValue
from teleclaude.core.origins import InputOrigin
from teleclaude.core.shutdown_drain import ShutdownRefusal
from teleclaude.core.voice_message_handler import handle_voice
from teleclaude.utils.transcript._utils import _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

# Final-output progress receipts in this adapter's origin_metadata section.
_FINAL_OUTPUT_VERSION_FIELD = "final_output_version"
_FINAL_OUTPUT_CHUNKS_SENT_FIELD = "final_output_chunks_sent"
_FINAL_OUTPUT_MESSAGE_ID_FIELD = "final_output_message_id"
_SHUTDOWN_REFUSAL_NOTICE = "TeleClaude is restarting and did not accept this message. Please send it again shortly."


class UiAdapter(  # pyright: ignore[reportIncompatibleMethodOverride]  # type: ignore[misc]
    MessageDeliveryMixin,
    BaseAdapter,
):
    """Base class for UI-enabled adapters.

    Delivers each finished turn once. Subclasses can override max_message_size
    and add platform-specific formatting.
    """

    # Adapter key for metadata storage (subclasses MUST override)
    ADAPTER_KEY: str = "unknown"

    # Platform API property name for the message ID (e.g. "id" for Discord/WhatsApp,
    # "message_id" for Telegram). Used when constructing platform API calls.
    OUTPUT_MESSAGE_ID_FIELD: str = "id"
    supports_message_deletion: bool = False

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

    def get_last_delivered_at(self, session: Session) -> datetime | None:
        """Read last_delivered_at from this adapter's origin_metadata section."""
        raw = self._origin_field(session, "last_delivered_at")
        if isinstance(raw, str):
            return _parse_timestamp(raw)
        return None

    async def set_last_delivered_at(self, session: Session, ts: datetime) -> None:
        """Write last_delivered_at to this adapter's origin_metadata section."""
        await self._set_origin_field(session, last_delivered_at=ts.isoformat())

    def get_final_output_due_at(self, session: Session) -> datetime | None:
        """Read this lane's outstanding final-output obligation, if it has one."""
        raw = self._origin_field(session, "final_output_due_at")
        if isinstance(raw, str):
            return _parse_timestamp(raw)
        return None

    def _origin_field(self, session: Session, field: str, default: object = None) -> object:
        """Read a field from this adapter's origin_metadata section."""
        return session.get_origin_section(self.ADAPTER_KEY).get(field, default)

    async def _set_origin_field(self, session: Session, **fields: JsonValue) -> None:
        """Write fields to this adapter's origin_metadata section (merge-write).

        Only ``fields`` are submitted. Sending the whole in-memory section would
        make this a read-modify-write around an atomic statement: a caller
        holding a snapshot taken before someone else's write would carry that
        stale section forward and silently revert their field. The merge patch
        is the unit of change, so concurrent writers touching different keys no
        longer clobber each other.
        """
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
        await db.update_origin_metadata(session.session_id, self.ADAPTER_KEY, dict(fields))
        # Keep in-memory session consistent for subsequent reads within the same request
        session.origin_metadata[self.ADAPTER_KEY] = section

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
        output_metadata: MessageMetadata | None = None,
    ) -> str | None:
        """Send each finished turn once, on its staged final pass.

        Live renders are declined: without in-place edits every render would
        reach the person as a separate message. ``EditableUiAdapter`` streams
        live output instead.
        """
        _ = (started_at, last_output_changed_at, exit_code, render_markdown)
        if not is_final or delivery_ts is None:
            return None
        metadata = (
            replace(output_metadata, content_format=ContentFormat.MARKDOWN)
            if output_metadata is not None
            else MessageMetadata(content_format=ContentFormat.MARKDOWN)
        )
        version = delivery_ts.isoformat()
        async with self._get_output_delivery_lock(session.session_id):
            fresh = await db.get_session(session.session_id)
            if fresh:
                session.origin_metadata = fresh.origin_metadata
            sent, last_message_id = self._final_output_progress(session, version)
            receipt = self.get_last_delivered_at(session)
            if receipt is not None and receipt >= delivery_ts:
                return last_message_id
            chunks, chunk_metadata = await self._split_for_sending(output, metadata)
            destination = resolve_destination(session, self.ADAPTER_KEY, metadata=chunk_metadata)
            for index in range(sent, len(chunks)):
                message_id = await self.send_message(
                    destination, chunks[index], metadata=chunk_metadata, multi_message=multi_message
                )
                last_message_id = str(message_id) if message_id else last_message_id
                await self._set_origin_field(
                    session,
                    final_output_version=version,
                    final_output_chunks_sent=index + 1,
                    final_output_message_id=last_message_id,
                )
            if not last_message_id:
                return None
            await self.set_last_delivered_at(session, delivery_ts)
            return last_message_id

    def _final_output_progress(self, session: Session, version: str) -> tuple[int, str | None]:
        """Chunks already sent for this final-output version, and the last message id.

        A retried final pass resumes after the chunks a failed attempt delivered.
        Read under the session's output lock, from fresh session state.
        """
        if self._origin_field(session, _FINAL_OUTPUT_VERSION_FIELD) != version:
            return 0, None
        sent = self._origin_field(session, _FINAL_OUTPUT_CHUNKS_SENT_FIELD, 0)
        message_id = self._origin_field(session, _FINAL_OUTPUT_MESSAGE_ID_FIELD)
        return (
            sent if isinstance(sent, int) else 0,
            message_id if isinstance(message_id, str) else None,
        )

    # === Output Message Management (Default Implementations) ===

    def _convert_markdown_for_platform(self, text: str) -> str:
        """Convert markdown to platform-specific format. Override for platform escaping."""
        return text

    @staticmethod
    def _fits_budget(text: str, max_bytes: int) -> bool:
        """Check if text fits within both char and byte budgets."""
        return len(text.encode("utf-8")) <= max_bytes

    async def _pre_handle_user_input(self, session: Session) -> None:
        """Called before handling user input - cleanup ephemeral messages.

        Every UI adapter uses the same durable next-input deletion set. Platform
        deletion remains adapter-owned; successful rows are removed one by one
        so a transient failure remains retryable.
        """
        if not self.supports_message_deletion:
            return
        pending = await db.get_pending_deletions(session.session_id, self.ADAPTER_KEY)
        if not pending:
            return
        destination = resolve_destination(session, self.ADAPTER_KEY)
        for message_id in pending:
            deleted = await self.delete_message(destination, message_id)
            if not deleted:
                continue
            await db.remove_pending_deletion(session.session_id, self.ADAPTER_KEY, message_id)

    async def _post_handle_user_input(self, session: Session, message_id: str) -> None:
        """Track accepted input for deletion unless it remains conversation history."""
        origin = InputOrigin(self.ADAPTER_KEY)
        if self.supports_message_deletion and not retains_human_conversation_input(origin):
            await db.add_pending_deletion(session.session_id, self.ADAPTER_KEY, message_id)

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
        *,
        retain_refusal: bool = False,
    ) -> object:
        """Run command with UI pre/post handling and broadcast to other adapters.

        A draining refusal is answered to the sender and re-raised. A caller whose place is recovered after the
        restart sets ``retain_refusal``: the refusal is re-raised without a notice, so the message stays unprocessed.
        """
        if message_id:
            await self.client.pre_handle_command(session, metadata.origin)

        try:
            result = await handler()
        except SessionMessageRejectedError as exc:
            if exc.reason is SessionMessageRejectionReason.ADMISSION_REFUSED:
                await self.send_error_feedback(session.session_id, str(exc))
            raise
        except ShutdownRefusal:
            if not retain_refusal:
                await self.answer_shutdown_refusal(session.session_id)
            raise

        if message_id:
            await self.client.post_handle_command(session, message_id, metadata.origin)

        return result

    async def answer_shutdown_refusal(self, session_id: str) -> None:
        """Tell the sender their input was refused because the daemon is restarting, so they can resend it.

        For an ingress that has no recovery of its own; a place recovered after the restart is not told to resend.
        """
        await self.send_error_feedback(session_id, _SHUTDOWN_REFUSAL_NOTICE)

    async def answer_refusal_of[T](self, session_id: str, work: Awaitable[T]) -> T | None:
        """Await input work, answering a draining refusal to the sender instead of dropping the input."""
        try:
            return await work
        except ShutdownRefusal:
            await self.answer_shutdown_refusal(session_id)
            return None

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

    async def on_session_status(self, session: Session, status: str) -> None:
        """React to a lifecycle status transition for this adapter's session.

        Dispatched by ``AdapterClient.dispatch_session_status`` after origin
        resolution — only the responsible adapter is invoked. The adapter owns
        its own status-filter policy: typing fires on ``active`` / ``accepted``
        for non-headless sessions.
        """
        if not self._presence_eligible(session, status):
            return
        await self._update_typing_presence(session, status)

    def _presence_eligible(self, session: Session, status: str) -> bool:
        """Typing gate: known status, non-headless session."""
        if status not in ("active", "accepted"):
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

    async def on_session_updated(self, session: Session, updated_fields: Mapping[str, object]) -> None:
        """React to a session-field update for this adapter's session.

        Default no-op. Subclasses override when they have UI state that
        depends on session metadata (e.g. Discord thread-topper).
        """
        _ = session, updated_fields
