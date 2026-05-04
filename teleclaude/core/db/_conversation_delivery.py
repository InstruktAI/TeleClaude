"""Mixin: conversation delivery cursor persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel import select

from .. import db_models


class _Unset:
    """Sentinel: ``pending_through_ts`` argument was omitted (leave value alone)."""


_UNSET = _Unset()


class DbConversationDeliveryMixin:
    """Directional delivery cursor helpers for conversation links."""

    async def get_conversation_delivery_state(
        self,
        *,
        link_id: str,
        source_session_id: str,
        target_session_id: str,
    ) -> db_models.ConversationDeliveryStateRow | None:
        """Return the persisted directional delivery cursor, if any."""
        stmt = select(db_models.ConversationDeliveryStateRow).where(
            db_models.ConversationDeliveryStateRow.link_id == link_id,
            db_models.ConversationDeliveryStateRow.source_session_id == source_session_id,
            db_models.ConversationDeliveryStateRow.target_session_id == target_session_id,
        )
        async with self._session() as db_session:
            return (await db_session.exec(stmt)).first()

    async def upsert_conversation_delivery_state(
        self,
        *,
        link_id: str,
        source_session_id: str,
        target_session_id: str,
        delivered_through_ts: str | None = None,
        pending_through_ts: str | None | _Unset = _UNSET,
    ) -> None:
        """Persist the directional cursor and/or in-flight pending bound.

        ``pending_through_ts`` semantics:
        - omitted (sentinel ``_UNSET``): leave the existing pending value alone.
        - explicit ``None``: clear the pending bound (atomic with delivered advance).
        - explicit timestamp: record this bound BEFORE a bundle send, so startup
          reconciliation can promote it on crash recovery without re-sending.
        """
        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            existing = await db_session.get(
                db_models.ConversationDeliveryStateRow,
                {
                    "link_id": link_id,
                    "source_session_id": source_session_id,
                    "target_session_id": target_session_id,
                },
            )
            if existing is not None:
                existing.delivered_through_ts = delivered_through_ts
                if not isinstance(pending_through_ts, _Unset):
                    existing.pending_through_ts = pending_through_ts
                existing.updated_at = now
                db_session.add(existing)
            else:
                pending_value = None if isinstance(pending_through_ts, _Unset) else pending_through_ts
                db_session.add(
                    db_models.ConversationDeliveryStateRow(
                        link_id=link_id,
                        source_session_id=source_session_id,
                        target_session_id=target_session_id,
                        delivered_through_ts=delivered_through_ts,
                        pending_through_ts=pending_value,
                        updated_at=now,
                    )
                )
            await db_session.commit()

    async def clear_conversation_delivery_state_for_link(self, *, link_id: str) -> int:
        """Remove delivery cursors for a severed link."""
        stmt = (
            update(db_models.ConversationDeliveryStateRow)
            .where(db_models.ConversationDeliveryStateRow.link_id == link_id)
            .values(delivered_through_ts=None, updated_at=datetime.now(UTC).isoformat())
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return int(result.rowcount or 0)
