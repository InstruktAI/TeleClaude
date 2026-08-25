"""Mixin: DbInboundMixin."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from .. import db_models
from ..dates import parse_iso_datetime
from ..inbound_types import InboundMessageType
from ..injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from ..models import MessageAuthor
from ._rows import InboundQueueRow

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_MISSING_PLATFORM_SOURCE_ERROR = "Platform-originated text requires a source occurrence key"
_DELIVERED_STATUS = "delivered"


def _decode_inbound_row(row: db_models.InboundQueue) -> InboundQueueRow:
    """Rebuild the typed ``InboundQueueRow`` from its ORM row, including caller provenance."""
    return InboundQueueRow(
        id=row.id or 0,
        session_id=row.session_id,
        origin=row.origin,
        message_type=row.message_type,
        text_kind=row.text_kind,
        source_feature=row.source_feature,
        occurrence_key=row.occurrence_key,
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
        caller_session_id=row.caller_session_id,
        caller_author_kind=row.caller_author_kind,
        caller_author_display=row.caller_author_display,
        caller_agent_runtime=row.caller_agent_runtime,
        caller_thinking_mode=row.caller_thinking_mode,
        caller_machine_role=row.caller_machine_role,
        caller_job_role=row.caller_job_role,
        caller_origin_prefix_len=row.caller_origin_prefix_len,
        caller_origin_suffix_len=row.caller_origin_suffix_len,
    )


class DbInboundMixin:
    """Inbound queue persistence helpers."""

    async def enqueue_inbound(
        self,
        session_id: str,
        origin: str,
        content: str,
        *,
        message_type: str = InboundMessageType.TEXT.value,
        text_kind: TranscriptEntryKind,
        source_feature: InjectedTextSourceFeature,
        occurrence_key: str | None,
        payload_json: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        source_message_id: str | None = None,
        source_channel_id: str | None = None,
        caller_session_id: str | None = None,
        caller_author: MessageAuthor | None = None,
        caller_job_role: str | None = None,
        caller_origin_prefix_len: int | None = None,
        caller_origin_suffix_len: int | None = None,
    ) -> int | None:
        """Persist an inbound message in the queue. Returns row ID or None on dedup skip.

        ``caller_session_id`` and ``caller_author`` carry the resolved
        originating-session identity at acceptance, before any transcript
        binding exists — present only when the caller is itself another
        session (e.g. a plain ``telec sessions send``); absent for ordinary
        human/adapter-originated input.
        """
        if text_kind is not TranscriptEntryKind.ORDINARY and not occurrence_key:
            raise ValueError(_MISSING_PLATFORM_SOURCE_ERROR)
        now = datetime.now(UTC).isoformat()
        row = db_models.InboundQueue(
            session_id=session_id,
            origin=origin,
            message_type=message_type,
            text_kind=text_kind.value,
            source_feature=source_feature.value,
            occurrence_key=occurrence_key,
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
            caller_session_id=caller_session_id,
            caller_author_kind=caller_author.kind.value if caller_author is not None else None,
            caller_author_display=caller_author.display if caller_author is not None else None,
            caller_agent_runtime=caller_author.agent_runtime if caller_author is not None else None,
            caller_thinking_mode=caller_author.thinking_mode if caller_author is not None else None,
            caller_machine_role=caller_author.machine_role if caller_author is not None else None,
            caller_job_role=caller_job_role,
            caller_origin_prefix_len=caller_origin_prefix_len,
            caller_origin_suffix_len=caller_origin_suffix_len,
        )
        async with self._session() as db_session:
            if source_message_id is not None:
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

    async def get_inbound_id_by_source(self, *, origin: str, source_message_id: str) -> int | None:
        """Return the accepted inbound row identified by the queue deduplication key."""
        statement = (
            select(db_models.InboundQueue.id)
            .where(db_models.InboundQueue.origin == origin)
            .where(db_models.InboundQueue.source_message_id == source_message_id)
        )
        async with self._session() as db_session:
            row_id = (await db_session.exec(statement)).first()
            return int(row_id) if row_id is not None else None

    async def claim_inbound(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """CAS claim of an inbound queue row for processing. Returns True if claimed."""
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

    async def mark_inbound_retry_exhausted(self, row_id: int, error: str, now_iso: str) -> None:
        """Terminalize one failed retry after recording its final delivery attempt."""
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(
                status="expired",
                processed_at=now_iso,
                attempt_count=db_models.InboundQueue.attempt_count + 1,
                next_retry_at=None,
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
            return [_decode_inbound_row(row) for row in rows]

    async def fetch_recent_delivered_caller_inbound(
        self,
        session_id: str,
        *,
        delivered_after_iso: str | None,
        limit: int = 20,
    ) -> list[InboundQueueRow]:
        """Return a session's most recently delivered caller-originated rows, newest first.

        ``delivered_after_iso`` bounds the result to rows delivered after that
        instant, so a caller can scope the lookup to one turn window.
        """
        statement = (
            select(db_models.InboundQueue)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status == _DELIVERED_STATUS)
            .where(db_models.InboundQueue.caller_session_id.is_not(None))  # type: ignore[union-attr]
            .where(db_models.InboundQueue.reflected_at.is_(None))  # type: ignore[union-attr]
            .order_by(db_models.InboundQueue.id.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        if delivered_after_iso is not None:
            statement = statement.where(db_models.InboundQueue.processed_at > delivered_after_iso)  # type: ignore[operator]
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_inbound_row(row) for row in rows]

    async def claim_inbound_reflection(self, row_id: int) -> bool:
        """One-shot CAS consumption of a row for reflection. Returns True when claimed."""
        stmt = (
            update(db_models.InboundQueue)
            .where(
                db_models.InboundQueue.id == row_id,
                db_models.InboundQueue.reflected_at.is_(None),  # type: ignore[union-attr]
            )
            .values(reflected_at=datetime.now(UTC).isoformat())
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def get_inbound_row(self, row_id: int) -> db_models.InboundQueue | None:
        """Fetch one accepted inbound row by id, including its caller-provenance columns."""
        async with self._session() as db_session:
            return await db_session.get(db_models.InboundQueue, row_id)

    async def expire_inbound_for_session(self, session_id: str, now_iso: str) -> int:
        """Mark all pending/failed inbound messages for a session as expired. Returns count."""
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
        stmt = (
            select(db_models.InboundQueue.session_id)
            .where(db_models.InboundQueue.status.in_(["pending", "failed"]))
            .distinct()
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def cleanup_inbound(self, older_than_iso: str) -> int:
        """Delete terminal inbound rows after their own retention interval."""
        stmt = (
            delete(db_models.InboundQueue)
            .where(db_models.InboundQueue.status.in_(["delivered", "expired"]))
            .where(db_models.InboundQueue.created_at < older_than_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    async def cleanup_orphan_inbound(self, now_iso: str) -> int:
        """Expire pending inbound rows whose target session is closed or missing."""
        live_session_ids = select(db_models.Session.session_id).where(
            db_models.Session.closed_at.is_(None),
            or_(
                db_models.Session.lifecycle_status.is_(None),
                db_models.Session.lifecycle_status != "closed",
            ),
        )
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.status.in_(["pending", "failed", "processing"]))
            .where(db_models.InboundQueue.session_id.notin_(live_session_ids))
            .values(
                status="expired",
                processed_at=now_iso,
                locked_at=None,
                last_error="target session closed or missing",
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    # ── Durable operations CRUD ────────────────────────────────────────
