"""Output delivery mixin for UI adapters.

Handles standard (edit-in-place) output delivery, footer management,
error feedback, and output formatting helpers.
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from instrukt_ai_logging import get_logger

import teleclaude.core.db as core_db
from teleclaude.config import config
from teleclaude.core.models import CleanupTrigger, MessageMetadata
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    strip_ansi_codes,
)

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

    class _OutputDeliveryHost(Protocol):  # pylint: disable=too-few-public-methods
        client: AdapterClient
        ADAPTER_KEY: str
        THREADED_OUTPUT: bool
        max_message_size: int
        _convert_markdown_for_platform: Callable[[str], str]
        _fit_output_to_limit: Callable[[str], str]
        _get_output_delivery_lock: Callable[[str], asyncio.Lock]
        _get_output_message_id: Callable[[Session], Awaitable[str | None]]
        _store_output_message_id: Callable[[Session, str], Awaitable[None]]
        _clear_output_message_id: Callable[[Session], Awaitable[None]]
        _get_footer_message_id: Callable[[Session], Awaitable[str | None]]
        _store_footer_message_id: Callable[[Session, str], Awaitable[None]]
        _clear_footer_message_id: Callable[[Session], Awaitable[None]]
        _cleanup_footer_if_present: Callable[[Session], Awaitable[None]]
        send_message: Callable[..., Awaitable[str | None]]
        edit_message: Callable[..., Awaitable[bool]]
        _metadata: Callable[..., MessageMetadata]
        _build_session_id_lines: Callable[[Session], str]


logger = get_logger(__name__)


@dataclass(frozen=True)
class DeliveryOptions:
    """Delivery flags shared between the lock wrapper and unlocked implementation."""

    multi_message: bool = False
    status_line: str = ""
    dedupe_by_digest: bool = True


def _delivery_options_from_kwargs(delivery_kwargs: MutableMapping[str, object]) -> DeliveryOptions:
    """Normalize delivery kwargs while preserving the legacy call surface for tests."""
    options = delivery_kwargs.pop("options", None)
    if isinstance(options, DeliveryOptions):
        return options
    return DeliveryOptions(
        multi_message=bool(delivery_kwargs.get("multi_message", False)),
        status_line=str(delivery_kwargs.get("status_line", "")),
        dedupe_by_digest=bool(delivery_kwargs.get("dedupe_by_digest", True)),
    )


class OutputDeliveryMixin:
    """Mixin providing output delivery for UiAdapter.

    Required from host class:
    - client: AdapterClient
    - ADAPTER_KEY: str
    - THREADED_OUTPUT: bool
    - max_message_size: int
    - _get_output_message_id(session) -> str | None
    - _store_output_message_id(session, message_id) -> None
    - _clear_output_message_id(session) -> None
    - _get_footer_message_id(session) -> str | None
    - _store_footer_message_id(session, message_id) -> None
    - _clear_footer_message_id(session) -> None
    - _cleanup_footer_if_present(session) -> None
    - send_message(session, text, metadata, ...) -> str | None
    - edit_message(session, message_id, text, metadata) -> bool
    - delete_message(session, message_id) -> bool
    - _convert_markdown_for_platform(text) -> str
    - _fit_output_to_limit(tmux_output) -> str
    """

    client: AdapterClient
    ADAPTER_KEY: str
    THREADED_OUTPUT: bool
    max_message_size: int

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Build metadata for threaded content messages. Override for platform-specific parse mode."""
        return MessageMetadata()

    async def send_output_update(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        session: Session,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: int | None = None,
        render_markdown: bool = False,
    ) -> str | None:
        """Send or edit output message - generic implementation.

        Truncates based on self.max_message_size, formats with status line,
        and always edits existing message (creates new only if edit fails).

        Subclasses can override _build_output_metadata() for platform-specific formatting.
        """
        # Suppress standard poller output when threaded output is active for this adapter.
        if self.THREADED_OUTPUT:
            logger.debug(
                "[UI_SEND_OUTPUT] Standard output suppressed for session %s on %s (threaded output active)",
                session.session_id,
                self.ADAPTER_KEY,
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
        host = cast("_OutputDeliveryHost", self)
        if render_markdown:
            if is_truncated:
                prefix = f"[...truncated, showing last {self.max_message_size} chars...]"
                max_body = max(self.max_message_size - len(prefix) - 2, 0)
                tmux_output = output[-max_body:] if max_body else ""
                display_output = f"{prefix}\n\n{tmux_output}" if tmux_output else prefix
            else:
                display_output = tmux_output

            display_output = host._convert_markdown_for_platform(display_output)
        else:
            display_output = host._fit_output_to_limit(tmux_output)

        # Platform-specific metadata (inline keyboards, etc.)
        metadata = self._build_output_metadata(session, is_truncated)

        return await self._deliver_output(
            session,
            display_output,
            metadata,
            status_line=status_line,
        )

    async def _deliver_output(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        **delivery_kwargs: object,
    ) -> str | None:
        """Unified output delivery: dedup, edit/send, footer management."""
        options = _delivery_options_from_kwargs(delivery_kwargs)
        host = cast("_OutputDeliveryHost", self)
        lock = host._get_output_delivery_lock(session.session_id)
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
        host = cast("_OutputDeliveryHost", self)
        options = _delivery_options_from_kwargs(delivery_kwargs)
        display_digest = sha256(text.encode("utf-8")).hexdigest()

        # Digest short-circuit is kept for non-threaded output updates.
        # Threaded mode dedupe belongs upstream in the coordinator.
        if options.dedupe_by_digest and session.last_output_digest == display_digest:
            return await host._get_output_message_id(session)

        # 2. Try edit existing
        if await self._try_edit_output_message(session, text, metadata):
            await core_db.db.update_session(session.session_id, last_output_digest=display_digest)
            await self._send_footer(session, status_line=options.status_line)
            return await host._get_output_message_id(session)

        # 3. Edit failed → cleanup footer, send new, send footer below
        await host._cleanup_footer_if_present(session)
        new_id = await host.send_message(
            session,
            text,
            metadata=metadata,
            multi_message=options.multi_message,
        )
        if new_id:
            await host._store_output_message_id(session, new_id)
            await core_db.db.update_session(session.session_id, last_output_digest=display_digest)
            await self._send_footer(session, status_line=options.status_line)
        return new_id

    async def _try_edit_output_message(self, session: Session, text: str, metadata: MessageMetadata) -> bool:
        """Try to edit existing output message, clear message_id if edit fails.

        Returns:
            True if edited successfully, False if no message_id or edit failed
        """
        host = cast("_OutputDeliveryHost", self)
        message_id = await host._get_output_message_id(session)
        logger.debug(
            "[TRY_EDIT] session=%s existing_message_id=%s",
            session.session_id,
            message_id if message_id else "None",
        )
        if not message_id:
            logger.debug("[TRY_EDIT] No existing message_id, will send new message")
            return False

        logger.debug("[TRY_EDIT] Attempting to edit message %s for session %s", message_id, session.session_id)
        success = await host.edit_message(session, message_id, text, metadata=metadata)
        logger.debug(
            "[TRY_EDIT] Edit result for message %s: %s",
            message_id,
            "SUCCESS" if success else "FAILED",
        )

        if not success:
            # Edit failed - clear stale message_id
            logger.warning("[TRY_EDIT] Failed to edit message %s, clearing stale message_id", message_id)
            await host._clear_output_message_id(session)

        return success

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error as feedback message to user.

        Args:
            session_id: Session that encountered error
            error_message: Human-readable error description
        """
        try:
            session = await core_db.db.get_session(session_id)
            if session:
                host = cast("_OutputDeliveryHost", self)
                await self.client.send_message(
                    session,
                    f"❌ {error_message}",
                    metadata=host._metadata(),
                    cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
                )
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            logger.error("Failed to send error feedback for session %s: %s", session_id, error)

    async def _send_footer(self, session: Session, status_line: str = "") -> str | None:
        """Send or edit footer message below output."""
        # Disable floating footer for threaded sessions (header strategy).
        if self.THREADED_OUTPUT:
            return None

        host = cast("_OutputDeliveryHost", self)
        footer_text = self._build_footer_text(session, status_line=status_line)
        metadata = self._build_footer_metadata(session)

        existing_id = await host._get_footer_message_id(session)
        logger.trace(
            "[FOOTER] session=%s existing_id=%s footer_len=%d",
            session.session_id,
            existing_id,
            len(footer_text),
        )
        if existing_id:
            success = await host.edit_message(session, existing_id, footer_text, metadata=metadata)
            if success:
                return existing_id
            # Edit failed (stale message) — clear tracked ID and skip.
            # Do NOT fall back to sending a new message here; the next
            # render cycle will create a fresh footer naturally.
            logger.debug("[FOOTER] Edit failed for session=%s, clearing stale id %s", session.session_id, existing_id)
            await host._clear_footer_message_id(session)
            return None

        new_id = await host.send_message(session, footer_text, metadata=metadata)
        logger.debug("[FOOTER] send_message returned %s for session=%s", new_id, session.session_id)
        if new_id:
            await host._store_footer_message_id(session, new_id)
        return new_id

    def _build_footer_text(self, session: Session, status_line: str = "") -> str:
        """Build footer text with session IDs first and status line last."""
        host = cast("_OutputDeliveryHost", self)
        parts: list[str] = []
        session_lines = host._build_session_id_lines(session)
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

    def _build_output_metadata(self, _session: Session, _is_truncated: bool) -> MessageMetadata:
        """Build platform-specific metadata for output messages.

        Override in subclasses to add inline keyboards, buttons, etc.

        Args:
            session: Session object
            is_truncated: Whether output was truncated

        Returns:
            Platform-specific MessageMetadata
        """
        return MessageMetadata()  # Default: no extra metadata

    def _build_footer_metadata(self, _session: Session) -> MessageMetadata:
        """Build platform-specific metadata for footer messages.

        Override in subclasses to add download buttons, etc.
        """
        return MessageMetadata()
