"""Mixin: DbInboundMixin."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models
from ..dates import parse_iso_datetime
from ._rows import InboundQueueRow

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbInboundMixin:
    async def enqueue_inbound(
        self,
        session_id: str,
        origin: str,
        content: str,
        *,
        message_type: str = "text",
        payload_json: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        source_message_id: str | None = None,
        source_channel_id: str | None = None,
    ) -> int | None:
        """Persist an inbound message in the queue. Returns row ID or None on dedup skip."""
        now = datetime.now(UTC).isoformat()
        row = db_models.InboundQueue(
            session_id=session_id,
            origin=origin,
            message_type=message_type,
            content=content,
            payload_json=payload_json,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
            status="pending",
            created_at=now,
            attempt_count=0,
            source_message_id=source_message_id,
            source_channel_id=source_channel_id,
        )
        async with self._session() as db_session:
            from sqlalchemy.exc import IntegrityError

            if source_message_id is not None:
                from sqlmodel import select

                existing = await db_session.exec(
                    select(db_models.InboundQueue.id)
                    .where(db_models.InboundQueue.origin == origin)
                    .where(db_models.InboundQueue.source_message_id == source_message_id)
                )
                if existing.first() is not None:
                    return None
            db_session.add(row)
            try:
                await db_session.commit()
                await db_session.refresh(row)
            except IntegrityError:
                return None
            if row.id is None:
                raise RuntimeError("Failed to insert inbound_queue row")
            return int(row.id)

    async def claim_inbound(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """CAS claim of an inbound queue row for processing. Returns True if claimed."""
        from sqlalchemy import or_, update

        stmt = (
            update(db_models.InboundQueue)
            .where(
                db_models.InboundQueue.id == row_id,
                db_models.InboundQueue.status.in_(["pending", "failed"]),
                or_(
                    db_models.InboundQueue.locked_at.is_(None),
                    db_models.InboundQueue.locked_at <= lock_cutoff_iso,
                ),
            )
            .values(locked_at=now_iso, status="processing")
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def mark_inbound_delivered(self, row_id: int, now_iso: str) -> None:
        """Mark an inbound queue row as delivered."""
        from sqlalchemy import update

        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(status="delivered", processed_at=now_iso, locked_at=None)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_inbound_expired(self, row_id: int, error: str, now_iso: str) -> None:
        """Mark an inbound queue row as expired (permanent drop)."""
        from sqlalchemy import update

        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(
                status="expired",
                processed_at=now_iso,
                last_error=error,
                locked_at=None,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_inbound_failed(
        self,
        row_id: int,
        error: str,
        now_iso: str,
        backoff_seconds: float,
    ) -> None:
        """Record an inbound delivery failure and schedule a retry."""
        from sqlalchemy import update

        dt = parse_iso_datetime(now_iso)
        if dt is None:
            dt = datetime.now(UTC)
        next_retry = (dt + timedelta(seconds=backoff_seconds)).isoformat()

        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(
                status="failed",
                attempt_count=db_models.InboundQueue.attempt_count + 1,
                next_retry_at=next_retry,
                last_error=error,
                locked_at=None,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def fetch_inbound_pending(
        self,
        session_id: str,
        limit: int,
        now_iso: str,
        lock_cutoff_iso: str,
    ) -> list[InboundQueueRow]:
        """Fetch pending/retryable inbound rows for a session, ordered by id ASC."""
        from sqlalchemy import or_
        from sqlmodel import select

        stmt = (
            select(db_models.InboundQueue)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status.in_(["pending", "failed"]))
            .where(
                or_(
                    db_models.InboundQueue.next_retry_at.is_(None),
                    db_models.InboundQueue.next_retry_at <= now_iso,
                )
            )
            .where(
                or_(
                    db_models.InboundQueue.locked_at.is_(None),
                    db_models.InboundQueue.locked_at <= lock_cutoff_iso,
                )
            )
            .order_by(db_models.InboundQueue.id.asc())  # type: ignore[arg-type]
            .limit(limit)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [
                InboundQueueRow(
                    id=row.id or 0,
                    session_id=row.session_id,
                    origin=row.origin,
                    message_type=row.message_type,
                    content=row.content,
                    payload_json=row.payload_json,
                    actor_id=row.actor_id,
                    actor_name=row.actor_name,
                    actor_avatar_url=row.actor_avatar_url,
                    status=row.status,
                    created_at=row.created_at,
                    attempt_count=row.attempt_count,
                    next_retry_at=row.next_retry_at,
                    last_error=row.last_error,
                    source_message_id=row.source_message_id,
                    source_channel_id=row.source_channel_id,
                )
                for row in rows
            ]

    async def expire_inbound_for_session(self, session_id: str, now_iso: str) -> int:
        """Mark all pending/failed inbound messages for a session as expired. Returns count."""
        from sqlalchemy import update

        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status.in_(["pending", "failed", "processing"]))
            .values(status="expired", processed_at=now_iso, locked_at=None)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    async def fetch_sessions_with_pending_inbound(self) -> list[str]:
        """Return distinct session_ids that have pending/failed inbound rows (for startup recovery)."""
        from sqlmodel import select

        stmt = (
            select(db_models.InboundQueue.session_id)
            .where(db_models.InboundQueue.status.in_(["pending", "failed"]))
            .distinct()
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def cleanup_inbound(self, older_than_iso: str) -> int:
        """Delete delivered/expired inbound rows older than threshold. Returns deleted count."""
        from sqlalchemy import delete

        stmt = (
            delete(db_models.InboundQueue)
            .where(db_models.InboundQueue.status.in_(["delivered", "expired"]))
            .where(db_models.InboundQueue.created_at < older_than_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    # ── Durable operations CRUD ────────────────────────────────────────
