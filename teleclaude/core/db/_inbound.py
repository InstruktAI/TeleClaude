"""Mixin: DbInboundMixin."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy import delete, or_, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from ...constants import InboundBindingDisposition
from .. import db_models
from ..dates import parse_iso_datetime
from ..inbound_types import InboundMessageType, TurnPartKind
from ..injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from ..models import MessageAuthor, MessageAuthorKind
from ._rows import InboundQueueRow

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_TURN_BINDING_CONFLICT_EVENT = "turn_binding_conflict_refused"
_TURN_BINDING_CUTOVER_MIGRATION = "052_add_accepted_turn_bindings"
_TURN_BINDING_CUTOVER_QUERY = "SELECT applied_at FROM schema_migrations WHERE version = :version"
_MISSING_PLATFORM_SOURCE_ERROR = "Platform-originated text requires a source occurrence key"


@dataclass(frozen=True)
class TurnAuthoredPartInput:
    """One ordered authored span to persist onto an accepted-turn binding."""

    part_kind: TurnPartKind
    span_start: int
    span_end: int
    original_source_session_id: str | None
    author: MessageAuthor
    author_job_role: str | None = None
    origin_surface: str | None = None


@dataclass(frozen=True)
class TurnAuthoredPartRecord:
    """One persisted authored part, decoded back to its typed author."""

    part_id: int
    part_kind: TurnPartKind
    span_start: int
    span_end: int
    original_source_session_id: str | None
    author: MessageAuthor
    author_job_role: str | None
    origin_surface: str | None


@dataclass(frozen=True)
class TurnReceiptEnvelopeInput:
    """One receipt and its canonical envelope/body spans in a native binding."""

    inbound_queue_id: int
    envelope_index: int
    occurrence_key: str
    text_kind: TranscriptEntryKind
    envelope_span: tuple[int, int]
    body_span: tuple[int, int]
    authored_part_id: int | None = None


@dataclass(frozen=True)
class TurnReceiptEnvelopeRecord:
    """One persisted receipt-correlated envelope span."""

    inbound_queue_id: int
    envelope_index: int
    occurrence_key: str
    text_kind: TranscriptEntryKind
    envelope_span: tuple[int, int]
    body_span: tuple[int, int]
    authored_part_id: int | None


@dataclass(frozen=True)
class NativeReference:
    """The runtime-qualified native transcript reference a binding is keyed to.

    Never a file offset or line number — the runtime's own stable entry id,
    qualified by runtime and native-session identity so it stays unambiguous
    across pane replacement and revival.
    """

    runtime: str
    native_session_id: str
    entry_id: str


@dataclass(frozen=True)
class AcceptedTurnBindingRecord:
    """A durable binding with its ordered authored parts."""

    binding_id: str
    session_id: str
    native_reference: NativeReference | None
    parts: list[TurnAuthoredPartRecord]
    receipt_envelopes: list[TurnReceiptEnvelopeRecord]

    def receipt_for_part(self, part_id: int) -> TurnReceiptEnvelopeRecord | None:
        """Return the receipt structurally associated with one authored body part."""
        return next((receipt for receipt in self.receipt_envelopes if receipt.authored_part_id == part_id), None)


def _decode_part_author(row: db_models.TurnAuthoredPartRow) -> MessageAuthor:
    return MessageAuthor(
        kind=MessageAuthorKind(row.author_kind),
        display=row.author_display,
        session_id=row.original_source_session_id,
        agent_runtime=row.author_agent_runtime,
        thinking_mode=row.author_thinking_mode,
        machine_role=row.author_machine_role,
    )


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

    async def get_inbound_row(self, row_id: int) -> db_models.InboundQueue | None:
        """Fetch one accepted inbound row by id, including its caller-provenance columns."""
        async with self._session() as db_session:
            return await db_session.get(db_models.InboundQueue, row_id)

    async def get_unbound_delivered_inbound(self, *, session_id: str) -> list[InboundQueueRow]:
        """Return delivered accepted rows for a session with no durable turn binding yet.

        Ordered by acceptance (id ASC) so callers process rows in the order
        they were accepted, matching the order their content appears in the
        native transcript.
        """
        associated_ids = select(db_models.TurnReceiptEnvelopeRow.inbound_queue_id)
        stmt = (
            select(db_models.InboundQueue)
            .where(db_models.InboundQueue.session_id == session_id)
            .where(db_models.InboundQueue.status == "delivered")
            .where(db_models.InboundQueue.binding_disposition.is_(None))
            .where(db_models.InboundQueue.id.notin_(associated_ids))
            .order_by(db_models.InboundQueue.id.asc())  # type: ignore[arg-type]
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(stmt)).all()
            return [_decode_inbound_row(row) for row in rows]

    async def get_bound_native_entry_ids(self, *, native_runtime: str, native_session_id: str) -> set[str]:
        """Return the set of native entry ids already claimed by a durable binding.

        Scoped to one runtime-qualified native session so a fresh pane after
        revival (a new ``native_session_id``) starts with an empty set.
        """
        stmt = select(db_models.AcceptedTurnBindingRow.native_entry_id).where(
            db_models.AcceptedTurnBindingRow.native_runtime == native_runtime,
            db_models.AcceptedTurnBindingRow.native_session_id == native_session_id,
            db_models.AcceptedTurnBindingRow.native_entry_id.is_not(None),
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return {entry_id for entry_id in result.all() if entry_id}

    async def get_conflicted_native_entry_ids(self, *, native_runtime: str, native_session_id: str) -> set[str]:
        """Return exact native entry ids durably measured for unresolved input conflicts."""
        stmt = select(db_models.BindingConflictCandidateRow.native_entry_id).where(
            db_models.BindingConflictCandidateRow.native_runtime == native_runtime,
            db_models.BindingConflictCandidateRow.native_session_id == native_session_id,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return {entry_id for entry_id in result.all() if entry_id}

    async def get_turn_binding_cutover(self) -> datetime | None:
        """Return the durable binding cutover timestamp, or ``None`` when unavailable."""
        stmt = text(_TURN_BINDING_CUTOVER_QUERY).bindparams(version=_TURN_BINDING_CUTOVER_MIGRATION)
        async with self._session() as db_session:
            row = (await db_session.exec(stmt)).first()
        return parse_iso_datetime(row[0]) if row is not None else None

    async def mark_inbound_binding_conflict(
        self,
        *,
        inbound_queue_id: int,
        candidates: list[NativeReference],
    ) -> bool:
        """Terminally disposition an ambiguous receipt and persist its exact candidate identities."""
        now = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.InboundQueue)
            .where(db_models.InboundQueue.id == inbound_queue_id)
            .where(db_models.InboundQueue.binding_disposition.is_(None))
            .values(binding_disposition=InboundBindingDisposition.INPUT_CONFLICT.value)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            if not result.rowcount:
                await db_session.rollback()
                return False
            for candidate in candidates:
                db_session.add(
                    db_models.BindingConflictCandidateRow(
                        inbound_queue_id=inbound_queue_id,
                        native_runtime=candidate.runtime,
                        native_session_id=candidate.native_session_id,
                        native_entry_id=candidate.entry_id,
                        created_at=now,
                    )
                )
            await db_session.commit()
            return True

    async def create_turn_binding(
        self,
        *,
        binding_id: str,
        session_id: str,
        native_reference: NativeReference | None,
        parts: list[TurnAuthoredPartInput],
        receipt_envelopes: list[TurnReceiptEnvelopeInput],
        generation_id: str,
    ) -> bool:
        """Bind a native turn to its accepted receipt when one exists, with ordered parts.

        A receipt association is idempotent: a row already bound is a replay of
        an already-processed acceptance and is skipped, returning ``False``.
        Receipt-less terminal bindings instead rely on the unique native reference.
        The native reference is unique per (runtime, native_session_id,
        entry_id) — a second attempt to bind the same native entry to a
        different row is refused (``False``) rather than silently doubling
        it; ambiguity detection is primarily the caller's, this is the
        durable backstop.

        ``generation_id`` cuts the turn's output generation in the SAME
        transaction as the binding: a process failure between two separate
        commits would otherwise leave a row permanently recorded as bound
        (so no later pass ever revisits it) with no generation ever created
        for it, silently dropping that turn's output forever. One commit,
        both rows, or neither.
        """
        async with self._session() as db_session:
            for receipt_envelope in receipt_envelopes:
                existing_envelope = (
                    await db_session.exec(
                        select(db_models.TurnReceiptEnvelopeRow).where(
                            db_models.TurnReceiptEnvelopeRow.inbound_queue_id == receipt_envelope.inbound_queue_id
                        )
                    )
                ).first()
                if existing_envelope is not None:
                    return False
            now = datetime.now(UTC).isoformat()
            db_session.add(
                db_models.AcceptedTurnBindingRow(
                    binding_id=binding_id,
                    session_id=session_id,
                    native_runtime=native_reference.runtime if native_reference else None,
                    native_session_id=native_reference.native_session_id if native_reference else None,
                    native_entry_id=native_reference.entry_id if native_reference else None,
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
                        origin_surface=part.origin_surface,
                    )
                )
            for receipt_envelope in receipt_envelopes:
                db_session.add(
                    db_models.TurnReceiptEnvelopeRow(
                        binding_id=binding_id,
                        inbound_queue_id=receipt_envelope.inbound_queue_id,
                        envelope_index=receipt_envelope.envelope_index,
                        occurrence_key=receipt_envelope.occurrence_key,
                        text_kind=receipt_envelope.text_kind.value,
                        envelope_span_start=receipt_envelope.envelope_span[0],
                        envelope_span_end=receipt_envelope.envelope_span[1],
                        body_span_start=receipt_envelope.body_span[0],
                        body_span_end=receipt_envelope.body_span[1],
                        authored_part_id=receipt_envelope.authored_part_id,
                    )
                )
            db_session.add(
                db_models.OutputGenerationRow(
                    generation_id=generation_id,
                    session_id=session_id,
                    binding_id=binding_id,
                    is_legacy=0,
                    created_at=now,
                )
            )
            try:
                await db_session.commit()
            except IntegrityError:
                await db_session.rollback()
                logger.warning(
                    _TURN_BINDING_CONFLICT_EVENT,
                    session_id=session_id,
                    binding_id=binding_id,
                    inbound_queue_id=None,
                )
                return False
            return True

    async def get_turn_binding_for_inbound(self, inbound_queue_id: int) -> AcceptedTurnBindingRecord | None:
        """Return the durable binding and its ordered authored parts for an accepted row."""
        async with self._session() as db_session:
            binding = (
                await db_session.exec(
                    select(db_models.AcceptedTurnBindingRow)
                    .join(
                        db_models.TurnReceiptEnvelopeRow,
                        db_models.TurnReceiptEnvelopeRow.binding_id == db_models.AcceptedTurnBindingRow.binding_id,
                    )
                    .where(db_models.TurnReceiptEnvelopeRow.inbound_queue_id == inbound_queue_id)
                )
            ).first()
            if binding is None:
                return None
            return await self._decode_turn_binding_record(db_session, binding)

    async def get_turn_binding(self, binding_id: str) -> AcceptedTurnBindingRecord | None:
        """Return the durable binding and its ordered authored parts by binding id.

        ``binding_id`` is deterministic (``f"{session_id}:{entry_id}"``), so a
        caller holding a native transcript entry can look up its binding
        directly — the structural counterpart to re-deriving attribution from
        rendered text. Returns ``None`` when the entry has not bound yet
        (not-yet-processed or an unresolved input conflict left it unbound).
        """
        async with self._session() as db_session:
            binding = await db_session.get(db_models.AcceptedTurnBindingRow, binding_id)
            if binding is None:
                return None
            return await self._decode_turn_binding_record(db_session, binding)

    async def get_turn_bindings_since(self, *, session_id: str, since_iso: str) -> list[AcceptedTurnBindingRecord]:
        """Return every durable binding created at/after a cursor, for one session.

        Pre-fetch for a caller that must correlate transcript entries to
        their bindings by native entry id without an async call per entry —
        the same batch-fetch-then-lookup shape ``get_peer_bundles_since``
        already uses for durable peer bundles.
        """
        async with self._session() as db_session:
            rows = (
                await db_session.exec(
                    select(db_models.AcceptedTurnBindingRow)
                    .where(db_models.AcceptedTurnBindingRow.session_id == session_id)
                    .where(db_models.AcceptedTurnBindingRow.created_at >= since_iso)
                )
            ).all()
            return [await self._decode_turn_binding_record(db_session, row) for row in rows]

    async def _decode_turn_binding_record(
        self, db_session: SqlAsyncSession, binding: db_models.AcceptedTurnBindingRow
    ) -> AcceptedTurnBindingRecord:
        part_rows = (
            await db_session.exec(
                select(db_models.TurnAuthoredPartRow)
                .where(db_models.TurnAuthoredPartRow.binding_id == binding.binding_id)
                .order_by(db_models.TurnAuthoredPartRow.part_id)
            )
        ).all()
        receipt_envelope_rows = (
            await db_session.exec(
                select(db_models.TurnReceiptEnvelopeRow)
                .where(db_models.TurnReceiptEnvelopeRow.binding_id == binding.binding_id)
                .order_by(db_models.TurnReceiptEnvelopeRow.envelope_span_start)
            )
        ).all()
        native_reference = (
            NativeReference(
                runtime=binding.native_runtime,
                native_session_id=binding.native_session_id,
                entry_id=binding.native_entry_id,
            )
            if binding.native_runtime and binding.native_session_id and binding.native_entry_id
            else None
        )
        return AcceptedTurnBindingRecord(
            binding_id=binding.binding_id,
            session_id=binding.session_id,
            native_reference=native_reference,
            parts=[
                TurnAuthoredPartRecord(
                    part_id=row.part_id,
                    part_kind=TurnPartKind(row.part_kind),
                    span_start=row.span_start,
                    span_end=row.span_end,
                    original_source_session_id=row.original_source_session_id,
                    author=_decode_part_author(row),
                    author_job_role=row.author_job_role,
                    origin_surface=row.origin_surface,
                )
                for row in part_rows
            ],
            receipt_envelopes=[
                TurnReceiptEnvelopeRecord(
                    inbound_queue_id=row.inbound_queue_id,
                    envelope_index=row.envelope_index,
                    occurrence_key=row.occurrence_key,
                    text_kind=TranscriptEntryKind(row.text_kind),
                    envelope_span=(row.envelope_span_start, row.envelope_span_end),
                    body_span=(row.body_span_start, row.body_span_end),
                    authored_part_id=row.authored_part_id,
                )
                for row in receipt_envelope_rows
            ],
        )

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
        """Delete delivered/expired inbound rows older than threshold that are durably bound.

        Binding-aware retention: a row past the cutoff with no durable
        ``accepted_turn_bindings`` row survives the sweep, because purging it
        would strand its provenance with no other durable record. Once the
        binding exists, the queue row may be removed — the binding and its
        authored parts retain the historical facts. Returns deleted count.
        """
        bound_inbound_ids = select(db_models.TurnReceiptEnvelopeRow.inbound_queue_id)
        stmt = (
            delete(db_models.InboundQueue)
            .where(db_models.InboundQueue.status.in_(["delivered", "expired"]))
            .where(db_models.InboundQueue.created_at < older_than_iso)
            .where(db_models.InboundQueue.id.in_(bound_inbound_ids))
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
