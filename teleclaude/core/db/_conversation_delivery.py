"""Mixin: conversation delivery cursor persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel import select

from teleclaude.constants import ConversationDeliveryDisposition, ConversationDeliveryRefusalReason

from .. import db_models
from ..models import MessageAuthor, MessageAuthorKind


class _Unset:
    """Sentinel: ``pending_through_ts`` argument was omitted (leave value alone)."""


_UNSET = _Unset()


@dataclass(frozen=True)
class PeerBundleSegmentInput:
    """One authored span to persist into a peer bundle, in delivery order."""

    original_source_session_id: str
    author: MessageAuthor
    author_job_role: str | None
    occurred_at: datetime
    body: str


@dataclass(frozen=True)
class PeerBundleSegmentRecord:
    """One persisted peer bundle segment, decoded back to its typed author."""

    segment_id: int
    original_source_session_id: str
    author: MessageAuthor
    author_job_role: str | None
    occurred_at: datetime
    body: str


@dataclass(frozen=True)
class PeerBundleWithSegments:
    """A durably persisted peer bundle with its ordered segments."""

    bundle_key: str
    created_at: str
    segments: list[PeerBundleSegmentRecord]


def _decode_segment_author(row: db_models.PeerBundleSegmentRow) -> MessageAuthor:
    """Rebuild the typed ``MessageAuthor`` from its persisted snapshot columns."""
    kind = MessageAuthorKind(row.author_kind)
    return MessageAuthor(
        kind=kind,
        display=row.author_display,
        session_id=row.original_source_session_id,
        agent_runtime=row.author_agent_runtime,
        thinking_mode=row.author_thinking_mode,
        machine_role=row.author_machine_role,
    )


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

    async def mark_conversation_delivery_disposition(
        self,
        *,
        link_id: str,
        source_session_id: str,
        target_session_id: str,
        disposition: ConversationDeliveryDisposition,
        entry_ref: str,
        reason: ConversationDeliveryRefusalReason,
    ) -> bool:
        """Persist one terminal outcome for a directional peer-delivery entry."""
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
            if existing is not None and existing.disposition_entry_ref == entry_ref:
                await db_session.rollback()
                return False
            if existing is None:
                db_session.add(
                    db_models.ConversationDeliveryStateRow(
                        link_id=link_id,
                        source_session_id=source_session_id,
                        target_session_id=target_session_id,
                        disposition=disposition.value,
                        disposition_entry_ref=entry_ref,
                        disposition_reason=reason.value,
                        updated_at=now,
                    )
                )
            else:
                existing.disposition = disposition.value
                existing.disposition_entry_ref = entry_ref
                existing.disposition_reason = reason.value
                existing.updated_at = now
                db_session.add(existing)
            await db_session.commit()
            return True

    async def get_all_conversation_delivery_states(self) -> list[db_models.ConversationDeliveryStateRow]:
        """Return every directional delivery cursor row, for legacy inventory."""
        async with self._session() as db_session:
            return list((await db_session.exec(select(db_models.ConversationDeliveryStateRow))).all())

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

    async def create_peer_bundle(
        self,
        *,
        bundle_key: str,
        link_id: str,
        source_session_id: str,
        target_session_id: str,
        segments: list[PeerBundleSegmentInput],
    ) -> bool:
        """Persist a structured peer bundle with its ordered segments, once.

        ``bundle_key`` is the caller's deterministic dedup key (mirroring the
        existing directional bundle key derivation). A duplicate key is a
        replay of an already-accepted bundle and is silently skipped —
        returns ``False``. Returns ``True`` when the bundle was newly
        persisted.
        """
        async with self._session() as db_session:
            existing = await db_session.get(db_models.PeerBundleRow, bundle_key)
            if existing is not None:
                return False
            now = datetime.now(UTC).isoformat()
            db_session.add(
                db_models.PeerBundleRow(
                    bundle_key=bundle_key,
                    link_id=link_id,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                    created_at=now,
                )
            )
            for segment_id, segment in enumerate(segments):
                db_session.add(
                    db_models.PeerBundleSegmentRow(
                        bundle_key=bundle_key,
                        segment_id=segment_id,
                        original_source_session_id=segment.original_source_session_id,
                        author_kind=segment.author.kind.value,
                        author_display=segment.author.display,
                        author_agent_runtime=segment.author.agent_runtime,
                        author_thinking_mode=segment.author.thinking_mode,
                        author_machine_role=segment.author.machine_role,
                        author_job_role=segment.author_job_role,
                        occurred_at=segment.occurred_at.isoformat(),
                        body=segment.body,
                    )
                )
            await db_session.commit()
            return True

    async def get_peer_bundles_since(self, *, target_session_id: str, since_iso: str) -> list[PeerBundleWithSegments]:
        """Return durable peer bundles delivered to a session at/after a cursor, oldest first.

        This is the structural read side of the peer carrier: a collector
        scanning its own transcript for forwarded content consumes these in
        order instead of re-deriving structure by parsing rendered text.
        """
        stmt = (
            select(db_models.PeerBundleRow)
            .where(db_models.PeerBundleRow.target_session_id == target_session_id)
            .where(db_models.PeerBundleRow.created_at >= since_iso)
            .order_by(db_models.PeerBundleRow.created_at)
        )
        async with self._session() as db_session:
            bundles = (await db_session.exec(stmt)).all()
        return [
            PeerBundleWithSegments(
                bundle_key=bundle.bundle_key,
                created_at=bundle.created_at,
                segments=await self.get_peer_bundle_segments(bundle_key=bundle.bundle_key),
            )
            for bundle in bundles
        ]

    async def get_peer_bundle_segments(self, *, bundle_key: str) -> list[PeerBundleSegmentRecord]:
        """Return a bundle's segments in delivery order, decoded to typed authors."""
        stmt = (
            select(db_models.PeerBundleSegmentRow)
            .where(db_models.PeerBundleSegmentRow.bundle_key == bundle_key)
            .order_by(db_models.PeerBundleSegmentRow.segment_id)
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(stmt)).all()
        return [
            PeerBundleSegmentRecord(
                segment_id=row.segment_id,
                original_source_session_id=row.original_source_session_id,
                author=_decode_segment_author(row),
                author_job_role=row.author_job_role,
                occurred_at=datetime.fromisoformat(row.occurred_at),
                body=row.body,
            )
            for row in rows
        ]
