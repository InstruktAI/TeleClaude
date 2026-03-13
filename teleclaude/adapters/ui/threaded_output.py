"""Threaded output mixin for UI adapters.

Handles append-only threaded message delivery with smart pagination,
continuation markers, and MarkdownV2 overflow splitting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

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
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


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

    if TYPE_CHECKING:
        import asyncio

        THREADED_OUTPUT: bool
        ADAPTER_KEY: str
        max_message_size: int
        THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS: int
        client: AdapterClient

        def _get_char_offset(self, session: Session) -> int: ...

        async def _set_char_offset(self, session: Session, value: int) -> None: ...

        async def _get_output_message_id(self, session: Session) -> str | None: ...

        async def _store_output_message_id(self, session: Session, message_id: str) -> None: ...

        async def _clear_output_message_id(self, session: Session) -> None: ...

        async def _cleanup_footer_if_present(self, session: Session) -> None: ...

        async def _get_badge_sent(self, session: Session) -> bool: ...

        async def _set_badge_sent(self, session: Session, value: bool) -> None: ...

        def _build_metadata_for_thread(self) -> MessageMetadata: ...

        async def _deliver_output_unlocked(
            self,
            session: Session,
            text: str,
            metadata: MessageMetadata,
            multi_message: bool = False,
            status_line: str = "",
            dedupe_by_digest: bool = True,
        ) -> str | None: ...

        async def _try_edit_output_message(self, session: Session, text: str, metadata: MessageMetadata) -> bool: ...

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

        @classmethod
        def _get_output_delivery_lock(cls, session_id: str) -> asyncio.Lock: ...

        def _build_session_id_lines(self, session: Session) -> str: ...

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

        lock = self._get_output_delivery_lock(session.session_id)
        async with lock:
            from teleclaude.core.db import db

            # Re-sync from DB so stale callers cannot replay already-consumed chunks.
            fresh = await db.get_session(session.session_id)
            if fresh:
                session.adapter_metadata = fresh.adapter_metadata
                session.output_message_id = fresh.output_message_id
                session.last_output_digest = fresh.last_output_digest

            # Convert once per render cycle. Telegram markdown conversion is not
            # idempotent; re-converting recursively can corrupt escape balance.
            converted_text = self._convert_markdown_for_platform(text)  # type: ignore[attr-defined]
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
        # HARD CLEANUP: Ensure no footer exists in threaded mode.
        await self._cleanup_footer_if_present(session)

        # 1. Get current offset and ID.
        char_offset = self._get_char_offset(session)
        output_message_id = await self._get_output_message_id(session)

        # 2. Slice text to get the "active" portion
        # If text is shorter than offset (e.g. restart?), reset offset
        if len(text) < char_offset:
            char_offset = 0
            await self._set_char_offset(session, 0)

        active_text = text[char_offset:]
        if not active_text and output_message_id:
            # No new text, nothing to do
            return output_message_id

        # 3. Session Badge (Header)
        # Discord uses thread topper as the canonical badge and should not emit
        # the legacy threaded badge block.
        if self.ADAPTER_KEY != "discord" and not await self._get_badge_sent(session):
            badge_text = self._build_session_id_lines(session)
            if badge_text:
                await self.client.send_message(
                    session,
                    badge_text,
                    metadata=MessageMetadata(parse_mode=None),
                    cleanup_trigger=CleanupTrigger.NEXT_TURN,
                    ephemeral=False,
                )
                await self._set_badge_sent(session, True)

        # 4. Add continuity markers
        is_markup_v2 = self._build_metadata_for_thread().parse_mode == "MarkdownV2"
        continuation_prefix = continuation_prefix_for_markdown_v2_state(_continuation_state) if is_markup_v2 else ""
        body_text = f"{continuation_prefix}{active_text}"
        display_text = body_text

        # 5. Check for overflow
        limit = self.max_message_size - 10
        if len(display_text) > limit:
            # --- OVERFLOW: SEAL AND SPLIT ---
            available_for_content = max(limit, 1)

            if is_markup_v2:
                chunk, consumed_display = truncate_markdown_v2_with_consumed(
                    body_text,
                    max_chars=available_for_content,
                    suffix="",
                )

                consumed_prefix = min(consumed_display, len(continuation_prefix))
                split_idx = consumed_display - consumed_prefix

                # If the split point would cut through a short leading entity
                # (like a compact link), try to move the boundary to the end
                # of that entity so it remains intact.
                entity_scan_limit = min(self.THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS, len(active_text))
                atomic_entity_threshold = min(
                    self.THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS,
                    max(32, available_for_content // 2),
                )
                leading_entity_span = leading_balanced_markdown_v2_entity_span(
                    active_text,
                    max_scan_chars=entity_scan_limit,
                )
                if 0 < leading_entity_span <= atomic_entity_threshold and split_idx < leading_entity_span:
                    atomic_chunk, atomic_consumed_display = truncate_markdown_v2_with_consumed(
                        f"{continuation_prefix}{active_text[:leading_entity_span]}",
                        max_chars=available_for_content,
                        suffix="",
                    )
                    atomic_consumed_prefix = min(atomic_consumed_display, len(continuation_prefix))
                    atomic_split_idx = atomic_consumed_display - atomic_consumed_prefix
                    if atomic_split_idx == leading_entity_span:
                        chunk = atomic_chunk
                        split_idx = atomic_split_idx

                if split_idx <= 0 and active_text:
                    split_idx = min(len(active_text), available_for_content)
                    chunk, _ = truncate_markdown_v2_with_consumed(
                        f"{continuation_prefix}{active_text[:split_idx]}",
                        max_chars=available_for_content,
                        suffix="",
                    )

                consumed_source = active_text[:split_idx]
                next_state = scan_markdown_v2_state(consumed_source, initial_state=_continuation_state)
            else:
                candidate = active_text[:available_for_content]
                last_space = candidate.rfind(" ")
                if last_space > (len(candidate) * 0.8):
                    split_idx = last_space
                else:
                    split_idx = available_for_content
                chunk = active_text[:split_idx]
                next_state = _continuation_state

            sealed_text = chunk

            # Commit this chunk
            seal_metadata = self._build_metadata_for_thread()
            if output_message_id:
                await self._try_edit_output_message(session, sealed_text, seal_metadata)
            else:
                new_id = await self.send_message(
                    session,
                    sealed_text,
                    metadata=seal_metadata,
                    multi_message=multi_message,
                )
                if new_id:
                    await self._store_output_message_id(session, new_id)

            # Update state for next message
            new_offset = char_offset + split_idx
            await self._set_char_offset(session, new_offset)
            await self._clear_output_message_id(session)

            # Recursive call to handle the remainder (same converted source text).
            return await self._send_threaded_output_unlocked(
                session,
                text,
                multi_message=multi_message,
                _continuation_state=next_state,
            )

        # --- NORMAL CASE: FIT AND SEND ---
        if is_markup_v2 and display_text:
            # Keep each intermediate threaded render syntactically valid for
            # MarkdownV2 by trimming partial entities and appending closers.
            display_text, _consumed = truncate_markdown_v2_with_consumed(
                display_text,
                max_chars=len(display_text),
                suffix="",
            )
            if not display_text:
                return output_message_id
        metadata = self._build_metadata_for_thread()
        return await self._deliver_output_unlocked(
            session,
            display_text,
            metadata,
            multi_message=multi_message,
            dedupe_by_digest=False,
        )
