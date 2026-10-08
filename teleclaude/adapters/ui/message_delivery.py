"""Standalone message delivery for every UiAdapter.

Sends a message once, overflowing it into continuation messages through the
adapter's markdown strategy. Required host attributes/methods (provided by
UiAdapter / BaseAdapter):
- ADAPTER_KEY: str
- max_message_size: int
- send_message(destination, text, *, metadata=None, multi_message=False) -> str
- _metadata(**kwargs) -> MessageMetadata
- _convert_markdown_for_platform(text) -> str
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from html import unescape
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui.threaded_output import OverflowContext, OverflowPlan
from teleclaude.core.db import db
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.models import ContentFormat, MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.delivery import Destination
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class MessageDeliveryMixin:
    """Standalone message delivery with markdown-aware overflow splitting."""

    ADAPTER_KEY: str
    max_message_size: int

    # Per-session lock to serialize output delivery and prevent concurrent
    # lanes from racing on delivery state.
    _output_delivery_locks: dict[str, asyncio.Lock] = {}

    if TYPE_CHECKING:

        async def send_message(
            self,
            destination: Destination,
            text: str,
            *,
            metadata: MessageMetadata | None = None,
            multi_message: bool = False,
        ) -> str: ...

        def _metadata(self, **kwargs: object) -> MessageMetadata: ...

        def _convert_markdown_for_platform(self, text: str) -> str: ...

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

    def _prepare_overflow_message(
        self,
        text: str,
        metadata: MessageMetadata | None,
    ) -> tuple[str, MessageMetadata | None]:
        """Prepare standalone UI message text before overflow splitting."""
        return text, metadata

    def _overflow_display_at_offset(self, text: str, offset: int) -> tuple[str, str]:
        continuation_state = self._scan_markdown_state(text[:offset], self._markdown_initial_state())
        continuation_prefix = self._continuation_prefix_for_state(continuation_state)
        return continuation_prefix, f"{continuation_prefix}{text[offset:]}"

    def _split_overflow_message(self, text: str) -> list[str]:
        """Split a standalone UI message with the same overflow engine as threaded output."""
        limit = max(self.max_message_size - 10, 1)
        if len(text) <= limit:
            return [self._balance_intermediate_chunk(text)] if text else [text]

        chunks: list[str] = []
        offset = 0
        while offset < len(text):
            continuation_prefix, display_text = self._overflow_display_at_offset(text, offset)
            if len(display_text) <= limit:
                final_chunk = self._balance_intermediate_chunk(display_text)
                if final_chunk:
                    chunks.append(final_chunk)
                break

            overflow_context = OverflowContext(
                continuation_prefix=continuation_prefix,
                available_for_content=limit,
            )
            overflow_plan = self._plan_overflow(text[offset:], overflow_context)
            if overflow_plan.chunk:
                chunks.append(overflow_plan.chunk)
            offset += overflow_plan.split_idx

        return chunks or [text]

    async def deliver_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> list[str]:
        """Deliver one standalone message through format dispatch and private splitting."""
        return await self._send_split_message(session, text, metadata=metadata, multi_message=multi_message)

    def _split_for_sending(
        self,
        text: str,
        metadata: MessageMetadata | None,
    ) -> tuple[list[str], MessageMetadata | None]:
        """Format *text* for this platform and split it into the messages that carry it."""
        converted_text, formatted_metadata = self._format_standalone_text(text, metadata)
        prepared_text, prepared_metadata = self._prepare_overflow_message(converted_text, formatted_metadata)
        return self._split_overflow_message(prepared_text), prepared_metadata

    async def _send_split_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> list[str]:
        """Send a standalone UI message, overflowing into continuation messages when needed."""
        chunks, prepared_metadata = self._split_for_sending(text, metadata)
        destination = resolve_destination(session, self.ADAPTER_KEY, metadata=prepared_metadata)
        lock = self._get_output_delivery_lock(session.session_id)
        async with lock:
            message_ids: list[str] = []
            for chunk in chunks:
                message_id = await self.send_message(
                    destination,
                    chunk,
                    metadata=prepared_metadata,
                    multi_message=multi_message,
                )
                if message_id:
                    message_ids.append(str(message_id))
            return message_ids

    def _format_standalone_text(
        self,
        text: str,
        metadata: MessageMetadata | None,
    ) -> tuple[str, MessageMetadata | None]:
        """Apply the declared format once before this adapter's private split/send flow."""
        if metadata is None or metadata.content_format is ContentFormat.PLAIN:
            return text, metadata
        if metadata.content_format is ContentFormat.MARKDOWN:
            return self._convert_markdown_for_platform(text), metadata
        if metadata.content_format is ContentFormat.HTML:
            return re.sub(r"<[^>]*>", "", unescape(text)), replace(
                metadata, content_format=ContentFormat.PLAIN, parse_mode=None
            )
        raise ValueError(f"Unsupported content format: {metadata.content_format}")

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

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error as feedback message to user.

        Args:
            session_id: Session that encountered error
            error_message: Human-readable error description
        """
        try:
            session = await db.get_session(session_id)
            if session:
                metadata = self._metadata()
                destination = resolve_destination(session, self.ADAPTER_KEY, metadata=metadata)
                await self.send_message(
                    destination,
                    f"❌ {error_message}",
                    metadata=metadata,
                )
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            logger.error("Failed to send error feedback for session %s: %s", session_id, error)
