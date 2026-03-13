"""Output delivery mixin for UI adapters.

Handles standard (edit-in-place) output delivery, footer management,
error feedback, and output formatting helpers.
"""

from __future__ import annotations

import time
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.models import CleanupTrigger, MessageMetadata
from teleclaude.utils import (
    format_active_status_line,
    format_completed_status_line,
    format_size,
    strip_ansi_codes,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


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

    if TYPE_CHECKING:
        import asyncio

        client: AdapterClient
        ADAPTER_KEY: str
        THREADED_OUTPUT: bool
        max_message_size: int

        async def _get_output_message_id(self, session: Session) -> str | None: ...

        async def _store_output_message_id(self, session: Session, message_id: str) -> None: ...

        async def _clear_output_message_id(self, session: Session) -> None: ...

        async def _get_footer_message_id(self, session: Session) -> str | None: ...

        async def _store_footer_message_id(self, session: Session, message_id: str) -> None: ...

        async def _clear_footer_message_id(self, session: Session) -> None: ...

        async def _cleanup_footer_if_present(self, session: Session) -> None: ...

        async def send_message(
            self,
            session: Session,
            text: str,
            *,
            metadata: MessageMetadata,
            multi_message: bool = False,
            cleanup_trigger: CleanupTrigger | None = None,
            ephemeral: bool = True,
        ) -> str | None: ...

        async def edit_message(
            self,
            session: Session,
            message_id: str,
            text: str,
            *,
            metadata: MessageMetadata,
        ) -> bool: ...

        async def delete_message(self, session: Session, message_id: str) -> bool: ...

        def _convert_markdown_for_platform(self, text: str) -> str: ...

        def _fit_output_to_limit(self, tmux_output: str) -> str: ...

        @classmethod
        def _get_output_delivery_lock(cls, session_id: str) -> asyncio.Lock: ...

        def _build_session_id_lines(self, session: Session) -> str: ...

        def _metadata(self) -> MessageMetadata: ...

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

    async def _deliver_output(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        multi_message: bool = False,
        status_line: str = "",
        dedupe_by_digest: bool = True,
    ) -> str | None:
        """Unified output delivery: dedup, edit/send, footer management."""
        lock = self._get_output_delivery_lock(session.session_id)
        async with lock:
            return await self._deliver_output_unlocked(
                session,
                text,
                metadata,
                multi_message=multi_message,
                status_line=status_line,
                dedupe_by_digest=dedupe_by_digest,
            )

    async def _deliver_output_unlocked(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata,
        multi_message: bool = False,
        status_line: str = "",
        dedupe_by_digest: bool = True,
    ) -> str | None:
        """Core output delivery logic. Caller must hold the session output lock."""
        display_digest = sha256(text.encode("utf-8")).hexdigest()

        # Digest short-circuit is kept for non-threaded output updates.
        # Threaded mode dedupe belongs upstream in the coordinator.
        if dedupe_by_digest and session.last_output_digest == display_digest:
            return await self._get_output_message_id(session)

        # 2. Try edit existing
        if await self._try_edit_output_message(session, text, metadata):
            from teleclaude.core.db import db

            await db.update_session(session.session_id, last_output_digest=display_digest)
            await self._send_footer(session, status_line=status_line)
            return await self._get_output_message_id(session)

        # 3. Edit failed → cleanup footer, send new, send footer below
        await self._cleanup_footer_if_present(session)
        new_id = await self.send_message(session, text, metadata=metadata, multi_message=multi_message)
        if new_id:
            await self._store_output_message_id(session, new_id)
            from teleclaude.core.db import db

            await db.update_session(session.session_id, last_output_digest=display_digest)
            await self._send_footer(session, status_line=status_line)
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
            from teleclaude.core.db import db

            session = await db.get_session(session_id)
            if session:
                await self.client.send_message(
                    session,
                    f"❌ {error_message}",
                    metadata=self._metadata(),  # type: ignore[attr-defined]
                    cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
                )
        except Exception as e:
            logger.error("Failed to send error feedback for session %s: %s", session_id, e)

    async def _send_footer(self, session: Session, status_line: str = "") -> str | None:
        """Send or edit footer message below output."""
        # Disable floating footer for threaded sessions (header strategy).
        if self.THREADED_OUTPUT:
            return None

        footer_text = self._build_footer_text(session, status_line=status_line)
        metadata = self._build_footer_metadata(session)

        existing_id = await self._get_footer_message_id(session)
        logger.trace(
            "[FOOTER] session=%s existing_id=%s footer_len=%d",
            session.session_id,
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
            logger.debug("[FOOTER] Edit failed for session=%s, clearing stale id %s", session.session_id, existing_id)
            await self._clear_footer_message_id(session)
            return None

        new_id = await self.send_message(session, footer_text, metadata=metadata)
        logger.debug("[FOOTER] send_message returned %s for session=%s", new_id, session.session_id)
        if new_id:
            await self._store_footer_message_id(session, new_id)
        return new_id

    def _build_footer_text(self, session: Session, status_line: str = "") -> str:
        """Build footer text with session IDs first and status line last."""
        parts: list[str] = []
        session_lines = self._build_session_id_lines(session)  # type: ignore[attr-defined]
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
