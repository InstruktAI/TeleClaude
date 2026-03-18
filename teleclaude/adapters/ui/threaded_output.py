"""Threaded output mixin for UI adapters.

Handles append-only threaded message delivery with smart pagination,
continuation markers, and MarkdownV2 overflow splitting.
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

import teleclaude.core.db as core_db
from teleclaude.core.models import CleanupTrigger, MessageMetadata
from teleclaude.utils.markdown import (
    MARKDOWN_V2_INITIAL_STATE,
    MarkdownV2State,
    continuation_prefix_for_markdown_v2_state,
    leading_balanced_markdown_v2_entity_span,
    scan_markdown_v2_state,
    truncate_markdown_v2_with_consumed,
)

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

    class _ThreadedOutputHost(Protocol):  # pylint: disable=too-few-public-methods
        THREADED_OUTPUT: bool
        ADAPTER_KEY: str
        max_message_size: int
        THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS: int
        client: AdapterClient
        _get_output_delivery_lock: Callable[[str], asyncio.Lock]
        _convert_markdown_for_platform: Callable[[str], str]
        _cleanup_footer_if_present: Callable[[Session], Awaitable[None]]
        _get_output_message_id: Callable[[Session], Awaitable[str | None]]
        _store_output_message_id: Callable[[Session, str], Awaitable[None]]
        _clear_output_message_id: Callable[[Session], Awaitable[None]]
        _get_char_offset: Callable[[Session], int]
        _set_char_offset: Callable[[Session, int], Awaitable[None]]
        _get_badge_sent: Callable[[Session], Awaitable[bool]]
        _set_badge_sent: Callable[[Session, bool], Awaitable[None]]
        _build_session_id_lines: Callable[[Session], str]
        _build_metadata_for_thread: Callable[[], MessageMetadata]
        _try_edit_output_message: Callable[[Session, str, MessageMetadata], Awaitable[bool]]
        _deliver_output_unlocked: Callable[..., Awaitable[str | None]]
        send_message: Callable[..., Awaitable[str | None]]


logger = get_logger(__name__)


@dataclass(frozen=True)
class OverflowPlan:
    """Plan for sealing one threaded output chunk and continuing with the remainder."""

    chunk: str
    split_idx: int
    next_state: MarkdownV2State


@dataclass(frozen=True)
class OverflowContext:
    """Inputs shared by the overflow planning helpers."""

    continuation_prefix: str
    continuation_state: MarkdownV2State
    available_for_content: int
    is_markup_v2: bool


@dataclass(frozen=True)
class ThreadDelivery:
    """Delivery inputs for the non-overflow threaded render path."""

    output_message_id: str | None
    is_markup_v2: bool
    multi_message: bool


class ThreadedOutputMixin:
    """Mixin providing threaded output delivery for UiAdapter.

    Required from host class:
    - THREADED_OUTPUT: bool
    - ADAPTER_KEY: str
    - max_message_size: int
    - THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS: int
    - client: AdapterClient
    - _get_char_offset(session) -> int
    - _set_char_offset(session, value) -> None
    - _get_output_message_id(session) -> str | None
    - _store_output_message_id(session, message_id) -> None
    - _clear_output_message_id(session) -> None
    - _cleanup_footer_if_present(session) -> None
    - _get_badge_sent(session) -> bool
    - _set_badge_sent(session, value) -> None
    - _build_metadata_for_thread() -> MessageMetadata
    - _deliver_output_unlocked(session, text, metadata, ...) -> str | None
    - _try_edit_output_message(session, text, metadata) -> bool
    - send_message(session, text, metadata, ...) -> str | None
    - _get_output_delivery_lock(session_id) -> asyncio.Lock
    - _build_session_id_lines(session) -> str
    """

    THREADED_OUTPUT: bool
    ADAPTER_KEY: str
    max_message_size: int
    THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS: int
    client: AdapterClient

    async def sync_threaded_session_state(self, session: Session) -> None:
        """Public wrapper for refreshing the mutable session output state."""
        await self._sync_threaded_session_state(session)

    async def send_threaded_output(
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
        _continuation_state: MarkdownV2State = MARKDOWN_V2_INITIAL_STATE,
    ) -> str | None:
        """Send or edit threaded output message with smart pagination."""
        # Skip threaded output for adapters that don't use it.
        if not self.THREADED_OUTPUT:
            return None

        host = cast("_ThreadedOutputHost", self)
        lock = host._get_output_delivery_lock(session.session_id)
        async with lock:
            await self._sync_threaded_session_state(session)

            # Convert once per render cycle. Telegram markdown conversion is not
            # idempotent; re-converting recursively can corrupt escape balance.
            converted_text = host._convert_markdown_for_platform(text)
            return await self._send_threaded_output_unlocked(
                session,
                converted_text,
                multi_message=multi_message,
                _continuation_state=_continuation_state,
            )

    async def _send_threaded_output_unlocked(
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
        _continuation_state: MarkdownV2State = MARKDOWN_V2_INITIAL_STATE,
    ) -> str | None:
        """Threaded-output core logic. Caller must hold the session output lock."""
        host = cast("_ThreadedOutputHost", self)
        # HARD CLEANUP: Ensure no footer exists in threaded mode.
        await host._cleanup_footer_if_present(session)

        # 1. Get current offset and ID.
        char_offset = await self._normalize_char_offset(session, text)
        output_message_id = await host._get_output_message_id(session)

        # 2. Slice text to get the "active" portion
        active_text = text[char_offset:]
        if not active_text and output_message_id:
            # No new text, nothing to do
            return output_message_id

        # 3. Session Badge (Header)
        await self._emit_thread_badge_if_needed(session)

        # 4. Add continuity markers
        is_markup_v2, continuation_prefix, display_text = self._build_thread_body(active_text, _continuation_state)

        # 5. Check for overflow
        limit = self.max_message_size - 10
        if len(display_text) > limit:
            overflow_context = OverflowContext(
                continuation_prefix=continuation_prefix,
                continuation_state=_continuation_state,
                available_for_content=max(limit, 1),
                is_markup_v2=is_markup_v2,
            )
            overflow_plan = self._plan_overflow(
                active_text,
                overflow_context,
            )
            await self._seal_thread_chunk(
                session,
                output_message_id,
                overflow_plan.chunk,
                multi_message=multi_message,
            )
            await host._set_char_offset(session, char_offset + overflow_plan.split_idx)
            await host._clear_output_message_id(session)

            # Recursive call to handle the remainder (same converted source text).
            return await self._send_threaded_output_unlocked(
                session,
                text,
                multi_message=multi_message,
                _continuation_state=overflow_plan.next_state,
            )

        # --- NORMAL CASE: FIT AND SEND ---
        return await self._deliver_thread_body(
            session,
            display_text,
            ThreadDelivery(
                output_message_id=output_message_id,
                is_markup_v2=is_markup_v2,
                multi_message=multi_message,
            ),
        )

    async def _sync_threaded_session_state(self, session: Session) -> None:
        """Refresh mutable session output state from the database before rendering."""
        fresh = await core_db.db.get_session(session.session_id)
        if fresh:
            session.adapter_metadata = fresh.adapter_metadata
            session.output_message_id = fresh.output_message_id
            session.last_output_digest = fresh.last_output_digest

    async def _normalize_char_offset(self, session: Session, text: str) -> int:
        """Reset an invalid char offset and return the effective offset."""
        host = cast("_ThreadedOutputHost", self)
        char_offset = host._get_char_offset(session)
        if len(text) < char_offset:
            await host._set_char_offset(session, 0)
            return 0
        return char_offset

    async def _emit_thread_badge_if_needed(self, session: Session) -> None:
        """Emit the session badge exactly once for adapters that use it."""
        host = cast("_ThreadedOutputHost", self)
        if self.ADAPTER_KEY == "discord" or await host._get_badge_sent(session):
            return

        badge_text = host._build_session_id_lines(session)
        if not badge_text:
            return

        await self.client.send_message(
            session,
            badge_text,
            metadata=MessageMetadata(parse_mode=None),
            cleanup_trigger=CleanupTrigger.NEXT_TURN,
            ephemeral=False,
        )
        await host._set_badge_sent(session, True)

    def _build_thread_body(
        self,
        active_text: str,
        continuation_state: MarkdownV2State,
    ) -> tuple[bool, str, str]:
        """Build the rendered body text for the current threaded chunk."""
        host = cast("_ThreadedOutputHost", self)
        is_markup_v2 = host._build_metadata_for_thread().parse_mode == "MarkdownV2"
        continuation_prefix = continuation_prefix_for_markdown_v2_state(continuation_state) if is_markup_v2 else ""
        return is_markup_v2, continuation_prefix, f"{continuation_prefix}{active_text}"

    def _plan_overflow(
        self,
        active_text: str,
        overflow_context: OverflowContext,
    ) -> OverflowPlan:
        """Choose the next chunk to seal when the current display body overflows."""
        if overflow_context.is_markup_v2:
            return self._plan_markdown_overflow(active_text, overflow_context)
        return self._plan_plain_overflow(
            active_text,
            overflow_context.continuation_state,
            overflow_context.available_for_content,
        )

    def _plan_markdown_overflow(
        self,
        active_text: str,
        overflow_context: OverflowContext,
    ) -> OverflowPlan:
        """Plan a MarkdownV2-safe overflow split."""
        body_text = f"{overflow_context.continuation_prefix}{active_text}"
        chunk, consumed_display = truncate_markdown_v2_with_consumed(
            body_text,
            max_chars=overflow_context.available_for_content,
            suffix="",
        )

        consumed_prefix = min(consumed_display, len(overflow_context.continuation_prefix))
        split_idx = consumed_display - consumed_prefix
        split_idx, chunk = self._maybe_extend_markdown_entity(active_text, overflow_context, split_idx, chunk)
        if split_idx <= 0 and active_text:
            split_idx = min(len(active_text), overflow_context.available_for_content)
            chunk, _ = truncate_markdown_v2_with_consumed(
                f"{overflow_context.continuation_prefix}{active_text[:split_idx]}",
                max_chars=overflow_context.available_for_content,
                suffix="",
            )

        consumed_source = active_text[:split_idx]
        next_state = scan_markdown_v2_state(consumed_source, initial_state=overflow_context.continuation_state)
        return OverflowPlan(chunk=chunk, split_idx=split_idx, next_state=next_state)

    def _maybe_extend_markdown_entity(
        self,
        active_text: str,
        overflow_context: OverflowContext,
        split_idx: int,
        chunk: str,
    ) -> tuple[int, str]:
        """Keep short leading Markdown entities intact when splitting."""
        entity_scan_limit = min(self.THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS, len(active_text))
        atomic_entity_threshold = min(
            self.THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS,
            max(32, overflow_context.available_for_content // 2),
        )
        leading_entity_span = leading_balanced_markdown_v2_entity_span(
            active_text,
            max_scan_chars=entity_scan_limit,
        )
        if not 0 < leading_entity_span <= atomic_entity_threshold or split_idx >= leading_entity_span:
            return split_idx, chunk

        atomic_chunk, atomic_consumed_display = truncate_markdown_v2_with_consumed(
            f"{overflow_context.continuation_prefix}{active_text[:leading_entity_span]}",
            max_chars=overflow_context.available_for_content,
            suffix="",
        )
        atomic_consumed_prefix = min(atomic_consumed_display, len(overflow_context.continuation_prefix))
        atomic_split_idx = atomic_consumed_display - atomic_consumed_prefix
        if atomic_split_idx == leading_entity_span:
            return atomic_split_idx, atomic_chunk
        return split_idx, chunk

    def _plan_plain_overflow(
        self,
        active_text: str,
        continuation_state: MarkdownV2State,
        available_for_content: int,
    ) -> OverflowPlan:
        """Plan a plain-text overflow split at a natural word boundary when possible."""
        candidate = active_text[:available_for_content]
        last_space = candidate.rfind(" ")
        split_idx = last_space if last_space > (len(candidate) * 0.8) else available_for_content
        return OverflowPlan(
            chunk=active_text[:split_idx],
            split_idx=split_idx,
            next_state=continuation_state,
        )

    async def _seal_thread_chunk(
        self,
        session: Session,
        output_message_id: str | None,
        sealed_text: str,
        *,
        multi_message: bool,
    ) -> None:
        """Commit a sealed overflow chunk before continuing with the remainder."""
        host = cast("_ThreadedOutputHost", self)
        seal_metadata = host._build_metadata_for_thread()
        if output_message_id:
            await host._try_edit_output_message(session, sealed_text, seal_metadata)
            return

        new_id = await host.send_message(
            session,
            sealed_text,
            metadata=seal_metadata,
            multi_message=multi_message,
        )
        if new_id:
            await host._store_output_message_id(session, new_id)

    async def _deliver_thread_body(
        self,
        session: Session,
        display_text: str,
        delivery: ThreadDelivery,
    ) -> str | None:
        """Deliver the current threaded body without digest-based dedupe."""
        if delivery.is_markup_v2 and display_text:
            # Keep each intermediate threaded render syntactically valid for
            # MarkdownV2 by trimming partial entities and appending closers.
            display_text, _consumed = truncate_markdown_v2_with_consumed(
                display_text,
                max_chars=len(display_text),
                suffix="",
            )
            if not display_text:
                return delivery.output_message_id

        host = cast("_ThreadedOutputHost", self)
        metadata = host._build_metadata_for_thread()
        return await host._deliver_output_unlocked(
            session,
            display_text,
            metadata,
            multi_message=delivery.multi_message,
            dedupe_by_digest=False,
        )
