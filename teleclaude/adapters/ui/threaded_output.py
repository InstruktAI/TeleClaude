"""Threaded output mixin for UI adapters.

Handles append-only threaded message delivery with smart pagination,
continuation markers, and markdown-aware overflow splitting.

Markdown strategy
-----------------
The mixin calls six methods on ``self`` and trusts the host to provide them.
``UiAdapter`` supplies plain-text defaults; each concrete adapter overrides
only what its dialect requires.  This file has zero knowledge of specific
markdown flavors — adding a new adapter never requires touching it.
"""
# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger

import teleclaude.core.db as core_db
from teleclaude.core.models import MessageMetadata

if TYPE_CHECKING:
    import asyncio  # pylint: disable=import-outside-toplevel
    from typing import Protocol

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

    class _ThreadedOutputHost(Protocol):  # pylint: disable=too-few-public-methods
        ADAPTER_KEY: str
        max_message_size: int
        THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS: int
        client: AdapterClient
        _get_output_delivery_lock: Callable[[str], asyncio.Lock]
        _convert_markdown_for_platform: Callable[[str], str]
        _get_output_message_id: Callable[[Session], Awaitable[str | None]]
        _store_output_message_id: Callable[[Session, str], Awaitable[None]]
        _clear_output_message_id: Callable[[Session], Awaitable[None]]
        _get_char_offset: Callable[[Session], int]
        _set_char_offset: Callable[[Session, int], Awaitable[None]]
        _build_metadata_for_thread: Callable[[], MessageMetadata]
        _try_edit_output_message: Callable[[Session, str, MessageMetadata], Awaitable[bool]]
        _deliver_output_unlocked: Callable[..., Awaitable[str | None]]
        send_message: Callable[..., Awaitable[str | None]]
        # Markdown strategy — provided by UiAdapter, overridden per adapter.
        _markdown_initial_state: Callable[[], Any]
        _continuation_prefix_for_state: Callable[[Any], str]
        _truncate_for_overflow: Callable[[str, int], tuple[str, int]]
        _scan_markdown_state: Callable[[str, Any], Any]
        _finalize_overflow_split: Callable[[str, OverflowContext, int, str], tuple[int, str]]
        _balance_intermediate_chunk: Callable[[str], str]


logger = get_logger(__name__)


@dataclass(frozen=True)
class OverflowPlan:
    """Plan for sealing one threaded output chunk and continuing with the remainder."""

    chunk: str
    split_idx: int
    next_state: Any  # opaque — owned by the adapter's markdown strategy


@dataclass(frozen=True)
class OverflowContext:
    """Inputs shared by the overflow planning helpers."""

    continuation_prefix: str
    continuation_state: Any  # opaque — owned by the adapter's markdown strategy
    available_for_content: int


@dataclass(frozen=True)
class ThreadDelivery:
    """Delivery inputs for the non-overflow threaded render path."""

    output_message_id: str | None
    multi_message: bool


class ThreadedOutputMixin:
    """Mixin providing threaded output delivery for UiAdapter.

    Required from host class (provided by UiAdapter defaults, overridden per adapter):
    - ADAPTER_KEY: str
    - max_message_size: int
    - THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS: int
    - client: AdapterClient
    - _get_char_offset(session) -> int
    - _set_char_offset(session, value) -> None
    - _get_output_message_id(session) -> str | None
    - _store_output_message_id(session, message_id) -> None
    - _clear_output_message_id(session) -> None
    - _build_metadata_for_thread() -> MessageMetadata
    - _deliver_output_unlocked(session, text, metadata, ...) -> str | None
    - _try_edit_output_message(session, text, metadata) -> bool
    - send_message(session, text, metadata, ...) -> str | None
    - _get_output_delivery_lock(session_id) -> asyncio.Lock
    - _markdown_initial_state() -> Any
    - _continuation_prefix_for_state(state) -> str
    - _truncate_for_overflow(body_text, max_chars) -> tuple[str, int]
    - _scan_markdown_state(consumed, state) -> Any
    - _finalize_overflow_split(active_text, ctx, split_idx, chunk) -> tuple[int, str]
    - _balance_intermediate_chunk(text) -> str
    """

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
        _continuation_state: Any = None,
    ) -> str | None:
        """Send or edit threaded output message with smart pagination."""
        host = cast("_ThreadedOutputHost", self)
        if _continuation_state is None:
            _continuation_state = host._markdown_initial_state()
        lock = host._get_output_delivery_lock(session.session_id)
        async with lock:
            await self._sync_threaded_session_state(session)

            converted_text = host._convert_markdown_for_platform(text)
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
                _continuation_state=_continuation_state,
            )
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
        _continuation_state: Any = None,
    ) -> str | None:
        """Threaded-output core logic. Caller must hold the session output lock."""
        host = cast("_ThreadedOutputHost", self)

        # 1. Get current offset and ID.
        char_offset = await self._normalize_char_offset(session, text)
        output_message_id = await host._get_output_message_id(session)
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

        # 3. Build display body with continuation markers.
        continuation_prefix = host._continuation_prefix_for_state(_continuation_state)
        display_text = f"{continuation_prefix}{active_text}"

        # 4. Check for overflow.
        limit = self.max_message_size - 10
        if len(display_text) > limit:
            overflow_context = OverflowContext(
                continuation_prefix=continuation_prefix,
                continuation_state=_continuation_state,
                available_for_content=max(limit, 1),
            )
            overflow_plan = self._plan_overflow(active_text, overflow_context)
            await self._seal_thread_chunk(
                session,
                output_message_id,
                overflow_plan.chunk,
                multi_message=multi_message,
            )
            await host._set_char_offset(session, char_offset + overflow_plan.split_idx)
            await host._clear_output_message_id(session)

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
                multi_message=multi_message,
            ),
        )

    async def _sync_threaded_session_state(self, session: Session) -> None:
        """Refresh mutable session output state from the database before rendering."""
        fresh = await core_db.db.get_session(session.session_id)
        if fresh:
            session.origin_metadata = fresh.origin_metadata
            session.last_output_digest = fresh.last_output_digest

    async def _normalize_char_offset(self, session: Session, text: str) -> int:
        """Reset an invalid char offset and return the effective offset."""
        host = cast("_ThreadedOutputHost", self)
        char_offset = host._get_char_offset(session)
        if len(text) < char_offset:
            await host._set_char_offset(session, 0)
            return 0
        return char_offset

    def _plan_overflow(
        self,
        active_text: str,
        overflow_context: OverflowContext,
    ) -> OverflowPlan:
        """Compute the next sealed chunk when the display body overflows."""
        host = cast("_ThreadedOutputHost", self)
        body_text = f"{overflow_context.continuation_prefix}{active_text}"
        chunk, consumed_display = host._truncate_for_overflow(body_text, overflow_context.available_for_content)

        consumed_prefix = min(consumed_display, len(overflow_context.continuation_prefix))
        split_idx = consumed_display - consumed_prefix

        split_idx, chunk = host._finalize_overflow_split(active_text, overflow_context, split_idx, chunk)

        # Ensure we always make progress (avoid infinite split at position 0).
        if split_idx <= 0 and active_text:
            split_idx = min(len(active_text), overflow_context.available_for_content)
            chunk, _ = host._truncate_for_overflow(
                f"{overflow_context.continuation_prefix}{active_text[:split_idx]}",
                overflow_context.available_for_content,
            )

        consumed_source = active_text[:split_idx]
        next_state = host._scan_markdown_state(consumed_source, overflow_context.continuation_state)
        return OverflowPlan(chunk=chunk, split_idx=split_idx, next_state=next_state)

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
        host = cast("_ThreadedOutputHost", self)
        if display_text:
            display_text = host._balance_intermediate_chunk(display_text)
            if not display_text:
                return delivery.output_message_id

        metadata = host._build_metadata_for_thread()
        return await host._deliver_output_unlocked(
            session,
            display_text,
            metadata,
            multi_message=delivery.multi_message,
            dedupe_by_digest=False,
        )
