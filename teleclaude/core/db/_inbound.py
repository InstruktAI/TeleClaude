"""Mixin: DbInboundMixin."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from .. import db_models
from ..dates import parse_iso_datetime
from ..inbound_errors import InboundHoldReason
from ..inbound_types import InboundBindingDisposition, InboundMessageType, TurnPartKind
from ..injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from ..models import MessageAuthor, MessageAuthorKind
from ._rows import InboundQueueRow

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_MISSING_PLATFORM_SOURCE_ERROR = "Platform-originated text requires a source occurrence key"
_DELIVERED_STATUS = "delivered"
_FAILED_STATUS = "failed"
_PENDING_STATUS = "pending"
_PROCESSING_STATUS = "processing"


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
        was_held=row.was_held,
        hold_notice_pending=row.hold_notice_pending,
        hold_notice_attempt_count=row.hold_notice_attempt_count,
        hold_notice_next_retry_at=row.hold_notice_next_retry_at,
        hold_notice_error=row.hold_notice_error,
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
        binding_disposition=row.binding_disposition,
        reflection_claimed_at=row.reflection_claimed_at,
        locked_at=row.locked_at,
        accepted_input_at=row.accepted_input_at,
        accepted_runtime_turn_id=row.accepted_runtime_turn_id,
    )


@dataclass(frozen=True)
class InboundAcceptanceEvidence:
    """The session clock instant and runtime turn identity recorded when a row was accepted.

    ``runtime_turn_id`` is ``None`` when the session had no native turn identity at acceptance.
    """

    accepted_input_at: datetime
    runtime_turn_id: str | None


@dataclass(frozen=True)
class NativeReference:
    """A native entry identifier qualified by its runtime and native session."""

    runtime: str
    native_session_id: str
    entry_id: str


@dataclass(frozen=True)
class TurnAuthoredPartInput:
    """One author-owned span that belongs to a bound native entry."""

    part_kind: TurnPartKind
    span_start: int
    span_end: int
    original_source_session_id: str | None
    author: MessageAuthor
    author_job_role: str | None = None


@dataclass(frozen=True)
class TurnAuthoredPartRecord(TurnAuthoredPartInput):
    """A persisted authored span with its stable order within the binding."""

    part_id: int = 0


@dataclass(frozen=True)
class TurnReceiptEnvelopeInput:
    """One accepted occurrence and its structurally matched envelope spans."""

    inbound_queue_id: int
    envelope_index: int
    occurrence_key: str
    envelope_span: tuple[int, int]
    body_span: tuple[int, int]
    authored_part_id: int | None


@dataclass(frozen=True)
class AcceptedTurnBindingRecord:
    """A binding and its ordered authored parts."""

    binding_id: str
    parts: tuple[TurnAuthoredPartRecord, ...]


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

    async def mark_inbound_expired(
        self,
        row_id: int,
        error: str,
        now_iso: str,
        *,
        hold_notice_pending: bool = False,
    ) -> None:
        """Mark an inbound queue row as expired (permanent drop)."""
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(
                status="expired",
                processed_at=now_iso,
                last_error=error,
                was_held=True if hold_notice_pending else db_models.InboundQueue.was_held,
                hold_notice_pending=hold_notice_pending,
                hold_notice_attempt_count=0,
                hold_notice_next_retry_at=None,
                hold_notice_error=None,
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

    async def fetch_inbound_hold_notices(self, session_id: str) -> list[InboundQueueRow]:
        """Fetch expired inbound rows whose conversation notice remains owed."""
        stmt = (
            select(db_models.InboundQueue)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status == "expired")
            .where(db_models.InboundQueue.hold_notice_pending.is_(True))
            .order_by(db_models.InboundQueue.id.asc())  # type: ignore[arg-type]
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(stmt)).all()
            return [_decode_inbound_row(row) for row in rows]

    async def claim_inbound_hold_notice(
        self,
        row_id: int,
        now_iso: str,
        lock_cutoff_iso: str,
    ) -> bool:
        """Claim one pending conversation notice for delivery."""
        stmt = (
            update(db_models.InboundQueue)
            .where(
                db_models.InboundQueue.id == row_id,
                db_models.InboundQueue.status == "expired",
                db_models.InboundQueue.hold_notice_pending.is_(True),
                or_(
                    db_models.InboundQueue.hold_notice_next_retry_at.is_(None),
                    db_models.InboundQueue.hold_notice_next_retry_at <= now_iso,
                ),
                or_(
                    db_models.InboundQueue.locked_at.is_(None),
                    db_models.InboundQueue.locked_at <= lock_cutoff_iso,
                ),
            )
            .values(locked_at=now_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def mark_inbound_hold_notice_delivered(self, row_id: int) -> None:
        """Clear a terminal row's pending notice after a channel receipt."""
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .where(db_models.InboundQueue.status == "expired")
            .values(
                hold_notice_pending=False,
                hold_notice_next_retry_at=None,
                hold_notice_error=None,
                locked_at=None,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_inbound_hold_notice_unaddressable(self, row_id: int, reason: str) -> None:
        """Retire a notice obligation with a durable terminal recipient reason."""
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .where(db_models.InboundQueue.status == "expired")
            .where(db_models.InboundQueue.hold_notice_pending.is_(True))
            .values(
                hold_notice_pending=False,
                hold_notice_next_retry_at=None,
                hold_notice_error=reason,
                locked_at=None,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_inbound_hold_notice_failed(
        self,
        row_id: int,
        error: str,
        now_iso: str,
        backoff_seconds: float,
    ) -> None:
        """Retain a failed notice obligation and schedule another channel attempt."""
        dt = parse_iso_datetime(now_iso)
        if dt is None:
            dt = datetime.now(UTC)
        next_retry = (dt + timedelta(seconds=backoff_seconds)).isoformat()
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .where(db_models.InboundQueue.status == "expired")
            .where(db_models.InboundQueue.hold_notice_pending.is_(True))
            .values(
                hold_notice_attempt_count=db_models.InboundQueue.hold_notice_attempt_count + 1,
                hold_notice_next_retry_at=next_retry,
                hold_notice_error=error,
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

    async def mark_inbound_held(
        self,
        row_id: int,
        now_iso: str,
        backoff_seconds: float,
        reason: InboundHoldReason,
    ) -> None:
        """Release a held inbound row for retry without consuming an attempt, recording why it waits."""
        dt = parse_iso_datetime(now_iso)
        if dt is None:
            dt = datetime.now(UTC)
        next_retry = (dt + timedelta(seconds=backoff_seconds)).isoformat()
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(
                status=_FAILED_STATUS,
                next_retry_at=next_retry,
                last_error=reason.value,
                was_held=True,
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

    async def get_inbound_row(self, row_id: int) -> db_models.InboundQueue | None:
        """Fetch one accepted inbound row by id, including its caller-provenance columns."""
        async with self._session() as db_session:
            return await db_session.get(db_models.InboundQueue, row_id)

    async def record_inbound_acceptance_evidence(
        self,
        row_id: int,
        *,
        accepted_input_at: datetime,
        runtime_turn_id: str | None,
    ) -> None:
        """Record on one row, in a single update, the session clock instant and turn identity of its acceptance."""
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == row_id)
            .values(
                accepted_input_at=accepted_input_at.isoformat(),
                accepted_runtime_turn_id=runtime_turn_id,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def get_inbound_acceptance_evidence(self, row_id: int) -> InboundAcceptanceEvidence | None:
        """Read a row's recorded acceptance evidence fresh; ``None`` when none was recorded.

        The instant is present exactly when the pair was recorded, so a legitimately null turn identity is
        distinguishable from missing evidence.
        """
        async with self._session() as db_session:
            result = await db_session.exec(
                select(
                    db_models.InboundQueue.accepted_input_at,
                    db_models.InboundQueue.accepted_runtime_turn_id,
                ).where(db_models.InboundQueue.id == row_id)
            )
            recorded = result.first()
        if recorded is None or recorded[0] is None:
            return None
        accepted_input_at = parse_iso_datetime(recorded[0])
        if accepted_input_at is None:
            return None
        return InboundAcceptanceEvidence(accepted_input_at=accepted_input_at, runtime_turn_id=recorded[1])

    async def get_unbound_delivered_caller_inbound(self, session_id: str) -> list[InboundQueueRow]:
        """Return post-cutover caller receipts awaiting a native-entry binding."""
        associated_ids = select(db_models.TurnReceiptEnvelopeRow.inbound_queue_id)
        statement = (
            select(db_models.InboundQueue)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status == _DELIVERED_STATUS)
            .where(db_models.InboundQueue.caller_session_id.is_not(None))  # type: ignore[union-attr]
            .where(db_models.InboundQueue.binding_disposition.is_(None))  # type: ignore[union-attr]
            .where(db_models.InboundQueue.id.notin_(associated_ids))
            .order_by(db_models.InboundQueue.id.asc())  # type: ignore[arg-type]
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_inbound_row(row) for row in rows]

    async def create_turn_binding(
        self,
        *,
        binding_id: str,
        session_id: str,
        native_reference: NativeReference,
        parts: list[TurnAuthoredPartInput],
        receipt: TurnReceiptEnvelopeInput,
    ) -> bool:
        """Atomically persist one native-entry correlation and its ordered authored spans."""
        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            existing = await db_session.exec(
                select(db_models.TurnReceiptEnvelopeRow.inbound_queue_id).where(
                    db_models.TurnReceiptEnvelopeRow.inbound_queue_id == receipt.inbound_queue_id
                )
            )
            if existing.first() is not None:
                return False
            db_session.add(
                db_models.AcceptedTurnBindingRow(
                    binding_id=binding_id,
                    session_id=session_id,
                    native_runtime=native_reference.runtime,
                    native_session_id=native_reference.native_session_id,
                    native_entry_id=native_reference.entry_id,
                    created_at=now,
                )
            )
            for part_id, part in enumerate(parts):
                db_session.add(
                    db_models.TurnAuthoredPartRow(
                        binding_id=binding_id,
                        part_id=part_id,
                        part_kind=part.part_kind.value,
                        span_start=part.span_start,
                        span_end=part.span_end,
                        original_source_session_id=part.original_source_session_id,
                        author_kind=part.author.kind.value,
                        author_display=part.author.display,
                        author_agent_runtime=part.author.agent_runtime,
                        author_thinking_mode=part.author.thinking_mode,
                        author_machine_role=part.author.machine_role,
                        author_job_role=part.author_job_role,
                    )
                )
            db_session.add(
                db_models.TurnReceiptEnvelopeRow(
                    binding_id=binding_id,
                    inbound_queue_id=receipt.inbound_queue_id,
                    envelope_index=receipt.envelope_index,
                    occurrence_key=receipt.occurrence_key,
                    envelope_span_start=receipt.envelope_span[0],
                    envelope_span_end=receipt.envelope_span[1],
                    body_span_start=receipt.body_span[0],
                    body_span_end=receipt.body_span[1],
                    authored_part_id=receipt.authored_part_id,
                )
            )
            try:
                await db_session.commit()
            except IntegrityError:
                await db_session.rollback()
                return False
            return True

    async def get_turn_binding(self, binding_id: str) -> AcceptedTurnBindingRecord | None:
        """Read a binding's parts in their durable projection order."""
        async with self._session() as db_session:
            binding = await db_session.get(db_models.AcceptedTurnBindingRow, binding_id)
            if binding is None:
                return None
            part_rows = (
                await db_session.exec(
                    select(db_models.TurnAuthoredPartRow)
                    .where(db_models.TurnAuthoredPartRow.binding_id == binding_id)
                    .order_by(db_models.TurnAuthoredPartRow.part_id)  # type: ignore[arg-type]
                )
            ).all()
            parts = tuple(
                TurnAuthoredPartRecord(
                    part_id=row.part_id,
                    part_kind=TurnPartKind(row.part_kind),
                    span_start=row.span_start,
                    span_end=row.span_end,
                    original_source_session_id=row.original_source_session_id,
                    author=MessageAuthor(
                        kind=MessageAuthorKind(row.author_kind),
                        display=row.author_display,
                        session_id=row.original_source_session_id,
                        agent_runtime=row.author_agent_runtime,
                        thinking_mode=row.author_thinking_mode,
                        machine_role=row.author_machine_role,
                    ),
                    author_job_role=row.author_job_role,
                )
                for row in part_rows
            )
            return AcceptedTurnBindingRecord(binding_id=binding.binding_id, parts=parts)

    async def mark_inbound_binding_conflict(self, row_id: int, candidate: NativeReference) -> None:
        """Fail closed for one occurrence whose candidate cannot be bound uniquely."""
        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            await db_session.exec(
                update(db_models.InboundQueue)
                .where(db_models.InboundQueue.id == row_id)
                .where(db_models.InboundQueue.binding_disposition.is_(None))  # type: ignore[union-attr]
                .values(binding_disposition=InboundBindingDisposition.INPUT_CONFLICT.value)
            )
            db_session.add(
                db_models.BindingConflictCandidateRow(
                    inbound_queue_id=row_id,
                    native_runtime=candidate.runtime,
                    native_session_id=candidate.native_session_id,
                    native_entry_id=candidate.entry_id,
                    created_at=now,
                )
            )
            try:
                await db_session.commit()
            except IntegrityError:
                await db_session.rollback()

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

    async def has_queued_inbound(self, session_id: str) -> bool:
        """Whether any inbound row for the session still waits: pending, retrying or held, or mid-delivery."""
        stmt = (
            select(db_models.InboundQueue.id)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status.in_([_PENDING_STATUS, _FAILED_STATUS, _PROCESSING_STATUS]))
            .limit(1)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return result.first() is not None

    async def fetch_sessions_with_pending_inbound(self) -> list[str]:
        """Return sessions with retryable inbound rows or pending hold notices."""
        stmt = (
            select(db_models.InboundQueue.session_id)
            .where(
                or_(
                    db_models.InboundQueue.status.in_(["pending", "failed"]),
                    db_models.InboundQueue.hold_notice_pending.is_(True),
                )
            )
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
            .where(db_models.InboundQueue.hold_notice_pending.is_(False))
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
