"""Threaded and standalone output delivery for UiAdapter.

Split out of ui_adapter.py to keep that module under the size guardrail.
Required host attributes/methods (provided by UiAdapter / BaseAdapter):
- ADAPTER_KEY: str
- max_message_size: int
- send_message(destination, text, *, metadata=None, multi_message=False) -> str
- edit_message(destination, message_id, text, *, metadata=None) -> bool
- _metadata(**kwargs) -> MessageMetadata
- _convert_markdown_for_platform(text) -> str
- _get_output_message_id(session) -> str | None (async)
- _store_output_message_id(session, message_id) -> None (async)
- _clear_output_message_id(session) -> None (async)
- _get_char_offset(session) -> int
- _set_char_offset(session, value) -> None (async)
- set_last_delivered_at(session, ts) -> None (async)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui.output_delivery import _delivery_options_from_kwargs
from teleclaude.adapters.ui.threaded_output import OverflowContext, OverflowPlan, ThreadDelivery
from teleclaude.core.db import db
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.models import MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.delivery import Destination
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_STALE_GENERATION_CHUNK_DROPPED_EVENT = "delivery_stale_generation_chunk_dropped"
_STALE_GENERATION_RENDER_DROPPED_EVENT = "delivery_stale_generation_render_dropped"


class OutputDeliveryMixin:
    """Threaded output pagination + standalone output delivery for UiAdapter."""

    ADAPTER_KEY: str
    max_message_size: int

    # Per-session lock to serialize output delivery and prevent concurrent
    # lanes from racing on output_message_id reads/writes.
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

        async def edit_message(
            self,
            destination: Destination,
            message_id: str,
            text: str,
            *,
            metadata: MessageMetadata | None = None,
        ) -> bool: ...

        def _metadata(self, **kwargs: object) -> MessageMetadata: ...

        def _convert_markdown_for_platform(self, text: str) -> str: ...

        async def _get_output_message_id(self, session: Session) -> str | None: ...

        async def _store_output_message_id(self, session: Session, message_id: str) -> None: ...

        async def _clear_output_message_id(self, session: Session) -> None: ...

        def _get_char_offset(self, session: Session) -> int: ...

        async def _set_char_offset(self, session: Session, value: int) -> None: ...

        async def set_last_delivered_at(self, session: Session, ts: datetime) -> None: ...

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
        generation_id: str | None = None,
    ) -> str | None:
        """Send or edit threaded output message with smart pagination.

        ``generation_id``, when provided, is the generation this render was
        computed against — carried through to the edit path so a late,
        stale-generation snapshot is dropped rather than applied to the
        current turn's message.
        """
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
                generation_id=generation_id,
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

    async def send_overflow_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> list[str]:
        """Send a standalone UI message, overflowing into continuation messages when needed."""
        prepared_text, prepared_metadata = self._prepare_overflow_message(text, metadata)
        chunks = self._split_overflow_message(prepared_text)
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

    async def _send_threaded_output_unlocked(
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
        *,
        generation_id: str | None = None,
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
        continuation_prefix, display_text = self._overflow_display_at_offset(text, char_offset)

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
                generation_id=generation_id,
            )
            await self._set_char_offset(session, char_offset + overflow_plan.split_idx)
            await self._clear_output_message_id(session)

            # Recurse: the new char_offset will re-derive continuation state
            # from text[:new_char_offset] on the next iteration.
            return await self._send_threaded_output_unlocked(
                session,
                text,
                multi_message=multi_message,
                generation_id=generation_id,
            )

        # --- NORMAL CASE: FIT AND SEND ---
        return await self._deliver_thread_body(
            session,
            display_text,
            ThreadDelivery(
                output_message_id=output_message_id,
                multi_message=multi_message,
                generation_id=generation_id,
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
        generation_id: str | None = None,
    ) -> None:
        """Commit a sealed overflow chunk before continuing with the remainder."""
        if generation_id is not None:
            current_generation = await db.get_latest_output_generation(session.session_id)
            if current_generation is not None and current_generation.generation_id != generation_id:
                logger.debug(
                    _STALE_GENERATION_CHUNK_DROPPED_EVENT,
                    adapter=self.ADAPTER_KEY,
                    session_id=session.session_id,
                    rendered_for_generation_id=generation_id,
                    current_generation_id=current_generation.generation_id,
                )
                return

        seal_metadata = self._build_metadata_for_thread()
        if output_message_id:
            await self._try_edit_output_message(session, sealed_text, seal_metadata)
            return

        destination = resolve_destination(session, self.ADAPTER_KEY, metadata=seal_metadata)
        new_id = await self.send_message(
            destination,
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
            generation_id=delivery.generation_id,
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

        # Late output cannot cross generations: a render computed for an
        # older turn is dropped outright — never edited into the current
        # message and never sent as a new one — if the session has since
        # bound a later turn. Checked before dedupe/edit/send so a stale
        # snapshot takes no action at all, matching "an older-turn snapshot
        # never edits the next turn's message, even when it arrives after a
        # later input was accepted."
        if options.generation_id is not None:
            current_generation = await db.get_latest_output_generation(session.session_id)
            if current_generation is not None and current_generation.generation_id != options.generation_id:
                logger.debug(
                    _STALE_GENERATION_RENDER_DROPPED_EVENT,
                    adapter=self.ADAPTER_KEY,
                    session_id=session.session_id,
                    rendered_for_generation_id=options.generation_id,
                    current_generation_id=current_generation.generation_id,
                )
                return await self._get_output_message_id(session)

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
        destination = resolve_destination(session, self.ADAPTER_KEY, metadata=metadata)
        new_id = await self.send_message(
            destination,
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
        destination = resolve_destination(session, self.ADAPTER_KEY, metadata=metadata)
        success = await self.edit_message(destination, message_id, text, metadata=metadata)
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
                metadata = self._metadata()
                destination = resolve_destination(session, self.ADAPTER_KEY, metadata=metadata)
                await self.send_message(
                    destination,
                    f"❌ {error_message}",
                    metadata=metadata,
                )
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            logger.error("Failed to send error feedback for session %s: %s", session_id, error)
