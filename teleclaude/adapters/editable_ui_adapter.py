"""UI adapter base for platforms whose messages can be edited in place.

Streams live agent output by editing one tracked message per output generation
and overflowing into continuation messages. Telegram and Discord extend it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui.delivery_mixin import OutputDeliveryMixin
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.models._types import JsonValue

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_TURN_BOUNDARY_DETECTED_EVENT = "ui_adapter_turn_boundary_detected"


class EditableUiAdapter(  # pyright: ignore[reportIncompatibleMethodOverride]  # type: ignore[misc]
    OutputDeliveryMixin,
    UiAdapter,
):
    """UiAdapter that streams live output by editing its tracked output message."""

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

    def _get_char_offset(self, session: Session) -> int:
        """Get adapter-specific char offset."""
        raw = self._origin_field(session, "char_offset", 0)
        return int(str(raw)) if raw is not None else 0

    async def _set_char_offset(self, session: Session, value: int) -> None:
        """Set adapter-specific char offset."""
        await self._set_origin_field(session, char_offset=value)

    async def _write_cleared_turn_state(self, session: Session, **extra_fields: JsonValue) -> None:
        await self._set_origin_field(
            session,
            char_offset=0,
            output_message_id=None,
            last_delivered_at=datetime.now(UTC).isoformat(),
            **extra_fields,
        )

    async def clear_turn_state(self, session: Session) -> None:
        """Reset threaded delivery receipts so the next render sends fresh.

        Called only from the generation-boundary detector below, never at
        acceptance: acceptance no longer clears any adapter delivery state
        (Task 9) — clearing here loses the edit target for output still in
        flight and reposts cumulative content as a new message, which is
        exactly the defect this delivery removes.
        """
        await self._write_cleared_turn_state(session)

    async def _maybe_clear_on_turn_boundary(self, session: Session) -> str | None:
        """Reset per-adapter delivery state when a new turn has started.

        Compares the session's current bound output generation (Task 8: cut
        when a queued receipt binds into its native transcript turn) to the
        anchor persisted in origin_metadata. A generation identity is never
        misordered the way a timestamp comparison can be — replaces the prior
        "latest genuine user message timestamp" comparison, the exact
        mechanism the Turn provenance invariants name as the defect
        ("Timestamp comparison misclassifies a late snapshot from an older
        turn"). This is the *only* point that clears adapter delivery state;
        acceptance (Task 9) never does. When the generation advances, the
        previous turn's tracking message must not be edited with new-turn
        content — it would overwrite displayed output and, on overflow,
        silently bury chunk 1 inside a stale message that has already
        scrolled away.

        Returns the session's current generation id (or ``None`` when no
        turn has bound yet), so the caller can stamp the render it is about
        to send with the generation it was computed against.
        """
        latest_generation = await db.get_latest_output_generation(session.session_id)
        if latest_generation is None:
            return None  # no bound turn yet for this session

        stored_generation_id = self._origin_field(session, "turn_anchor_generation_id")

        if not isinstance(stored_generation_id, str) or not stored_generation_id:
            await self._set_origin_field(session, turn_anchor_generation_id=latest_generation.generation_id)
            return latest_generation.generation_id

        if latest_generation.generation_id == stored_generation_id:
            return latest_generation.generation_id

        # New turn: clear delivery state so the next render creates a fresh message.
        await self.clear_turn_state(session)
        await self._set_origin_field(session, turn_anchor_generation_id=latest_generation.generation_id)
        logger.debug(
            _TURN_BOUNDARY_DETECTED_EVENT,
            adapter=self.ADAPTER_KEY,
            session_id=session.session_id,
            previous_generation_id=stored_generation_id,
            new_generation_id=latest_generation.generation_id,
        )
        return latest_generation.generation_id

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
        """Handle live output pushed by the daemon-owned coordinator."""
        _ = (started_at, last_output_changed_at, is_final, exit_code, render_markdown)
        generation_id = await self._maybe_clear_on_turn_boundary(session)
        return await self.send_threaded_output(
            session,
            output,
            multi_message=multi_message,
            delivery_ts=delivery_ts,
            generation_id=generation_id,
            metadata=output_metadata,
        )

    async def _clear_output_message_id(self, session: Session) -> None:
        """Clear output message ID in this adapter's origin_metadata section."""
        await self._set_origin_field(session, output_message_id=None)
        logger.debug("Cleared output_message_id: adapter=%s session=%s", self.ADAPTER_KEY, session.session_id)
