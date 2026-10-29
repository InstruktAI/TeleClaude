"""Mixin: output generation identity, per-consumer cursors, and receipts.

A generation is the durable identity of one cut turn boundary. Each delivery
consumer (origin adapter, admin mirror, any other enabled lane) advances its
own cursor and holds its own per-generation receipt, so one consumer's
progress can never suppress or overwrite another's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import delete, exists, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import select

from .. import db_models
from ..models import GenerationHandle
from .stores import DaemonStore


class DiscordSendIntentStatus(StrEnum):
    """The dispositions of a durable Discord send intent."""

    PENDING = "pending"
    RESOLVED = "resolved"
    OMITTED = "omitted"
    REPLAYED = "replayed"


_TERMINAL_INTENT_STATUSES = (
    DiscordSendIntentStatus.RESOLVED,
    DiscordSendIntentStatus.OMITTED,
    DiscordSendIntentStatus.REPLAYED,
)


@dataclass(frozen=True)
class DiscordSendIntent:
    """A durable Discord webhook create intent."""

    intent_id: str
    session_id: str
    generation_id: str
    channel_id: str
    status: str
    platform_message_id: str | None
    replays_intent_id: str | None


def _decode_intent(row: db_models.DiscordSendIntentRow) -> DiscordSendIntent:
    return DiscordSendIntent(
        intent_id=row.intent_id,
        session_id=row.session_id,
        generation_id=row.generation_id,
        channel_id=row.channel_id,
        status=row.status,
        platform_message_id=row.platform_message_id,
        replays_intent_id=row.replays_intent_id,
    )


@dataclass(frozen=True)
class OutputGeneration:
    """A durable generation identity."""

    generation_id: str
    session_id: str
    native_runtime: str | None
    native_session_id: str | None
    native_entry_id: str | None
    binding_id: str | None
    is_legacy: bool
    created_at: datetime


def _decode_generation(row: db_models.OutputGenerationRow) -> OutputGeneration:
    return OutputGeneration(
        generation_id=row.generation_id,
        session_id=row.session_id,
        native_runtime=row.native_runtime,
        native_session_id=row.native_session_id,
        native_entry_id=row.native_entry_id,
        binding_id=row.binding_id,
        is_legacy=bool(row.is_legacy),
        created_at=datetime.fromisoformat(row.created_at),
    )


class DbOutputGenerationsMixin:
    """Generation, consumer-cursor, and consumer-receipt persistence helpers."""

    async def create_output_generation(
        self,
        *,
        generation_id: str,
        session_id: str,
        native_runtime: str | None = None,
        native_session_id: str | None = None,
        native_entry_id: str | None = None,
        binding_id: str | None = None,
        is_legacy: bool = False,
    ) -> OutputGeneration:
        """Persist a new generation identity. Idempotent on ``generation_id``."""
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            existing = await db_session.get(db_models.OutputGenerationRow, generation_id)
            if existing is not None:
                return _decode_generation(existing)
            now = datetime.now(UTC).isoformat()
            row = db_models.OutputGenerationRow(
                generation_id=generation_id,
                session_id=session_id,
                native_runtime=native_runtime,
                native_session_id=native_session_id,
                native_entry_id=native_entry_id,
                binding_id=binding_id,
                is_legacy=int(is_legacy),
                created_at=now,
            )
            db_session.add(row)
            await db_session.commit()
            return _decode_generation(row)

    async def get_output_generation(self, generation_id: str) -> OutputGeneration | None:
        """Return one generation by id."""
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            row = await db_session.get(db_models.OutputGenerationRow, generation_id)
            return _decode_generation(row) if row is not None else None

    async def get_latest_output_generation(self, session_id: str) -> OutputGeneration | None:
        """Return the most recently cut generation for a session, if any."""
        stmt = (
            select(db_models.OutputGenerationRow)
            .where(db_models.OutputGenerationRow.session_id == session_id)
            .order_by(db_models.OutputGenerationRow.created_at.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            row = (await db_session.exec(stmt)).first()
            return _decode_generation(row) if row is not None else None

    async def get_generation_handle(self, *, session_id: str, consumer: str) -> GenerationHandle | None:
        """Fetch the session's current generation plus one consumer's cursor and receipt.

        Returns the shared typed value adapters read instead of reconstructing
        turn identity from separate generation/cursor/receipt lookups, or
        ``None`` when the session has no cut generation yet.
        """
        generation = await self.get_latest_output_generation(session_id)
        if generation is None:
            return None
        cursor = await self.get_consumer_cursor(session_id=session_id, consumer=consumer)
        receipt = await self.get_consumer_receipt(
            session_id=session_id, consumer=consumer, generation_id=generation.generation_id
        )
        return GenerationHandle(
            generation_id=generation.generation_id,
            session_id=generation.session_id,
            binding_id=generation.binding_id,
            is_legacy=generation.is_legacy,
            consumer=consumer,
            cursor_char_offset=cursor.char_offset if cursor is not None else 0,
            receipt_platform_message_id=receipt.platform_message_id if receipt is not None else None,
            receipt_delivered_char_offset=receipt.delivered_char_offset if receipt is not None else 0,
        )

    async def get_consumer_cursor(self, *, session_id: str, consumer: str) -> db_models.OutputConsumerCursorRow | None:
        """Return one consumer's delivery cursor for a session, if any."""
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            return await db_session.get(
                db_models.OutputConsumerCursorRow, {"session_id": session_id, "consumer": consumer}
            )

    async def upsert_consumer_cursor(
        self,
        *,
        session_id: str,
        consumer: str,
        generation_id: str | None,
        char_offset: int,
    ) -> None:
        """Persist one consumer's delivery cursor, independent of every other consumer."""
        now = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            existing = await db_session.get(
                db_models.OutputConsumerCursorRow, {"session_id": session_id, "consumer": consumer}
            )
            if existing is not None:
                existing.generation_id = generation_id
                existing.char_offset = char_offset
                existing.updated_at = now
                db_session.add(existing)
            else:
                db_session.add(
                    db_models.OutputConsumerCursorRow(
                        session_id=session_id,
                        consumer=consumer,
                        generation_id=generation_id,
                        char_offset=char_offset,
                        updated_at=now,
                    )
                )
            await db_session.commit()

    async def get_consumer_receipt(
        self, *, session_id: str, consumer: str, generation_id: str
    ) -> db_models.OutputConsumerReceiptRow | None:
        """Return one consumer's edit-target receipt for a specific generation, if any."""
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            return await db_session.get(
                db_models.OutputConsumerReceiptRow,
                {"session_id": session_id, "consumer": consumer, "generation_id": generation_id},
            )

    async def upsert_consumer_receipt(
        self,
        *,
        session_id: str,
        consumer: str,
        generation_id: str,
        platform_message_id: str | None,
        delivered_char_offset: int,
    ) -> None:
        """Persist one consumer's edit target and delivered offset for one generation."""
        now = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            existing = await db_session.get(
                db_models.OutputConsumerReceiptRow,
                {"session_id": session_id, "consumer": consumer, "generation_id": generation_id},
            )
            if existing is not None:
                existing.platform_message_id = platform_message_id
                existing.delivered_char_offset = delivered_char_offset
                existing.updated_at = now
                db_session.add(existing)
            else:
                db_session.add(
                    db_models.OutputConsumerReceiptRow(
                        session_id=session_id,
                        consumer=consumer,
                        generation_id=generation_id,
                        platform_message_id=platform_message_id,
                        delivered_char_offset=delivered_char_offset,
                        updated_at=now,
                    )
                )
            await db_session.commit()

    async def create_discord_send_intent(
        self,
        *,
        intent_id: str,
        session_id: str,
        generation_id: str,
        channel_id: str,
    ) -> DiscordSendIntent:
        """Persist a pending webhook create intent before dispatch. Idempotent on ``intent_id``."""
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            existing = await db_session.get(db_models.DiscordSendIntentRow, intent_id)
            if existing is not None:
                return _decode_intent(existing)
            now = datetime.now(UTC).isoformat()
            row = db_models.DiscordSendIntentRow(
                intent_id=intent_id,
                session_id=session_id,
                generation_id=generation_id,
                channel_id=channel_id,
                status=DiscordSendIntentStatus.PENDING,
                created_at=now,
            )
            db_session.add(row)
            await db_session.commit()
            return _decode_intent(row)

    async def get_discord_send_intent(self, intent_id: str) -> DiscordSendIntent | None:
        """Return one Discord send intent by id."""
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            row = await db_session.get(db_models.DiscordSendIntentRow, intent_id)
            return _decode_intent(row) if row is not None else None

    async def get_pending_discord_send_intents(self, *, session_id: str | None = None) -> list[DiscordSendIntent]:
        """Return every intent still awaiting a terminal disposition (restart reconciliation target)."""
        stmt = select(db_models.DiscordSendIntentRow).where(
            db_models.DiscordSendIntentRow.status == DiscordSendIntentStatus.PENDING
        )
        if session_id is not None:
            stmt = stmt.where(db_models.DiscordSendIntentRow.session_id == session_id)
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            rows = (await db_session.exec(stmt)).all()
            return [_decode_intent(row) for row in rows]

    async def resolve_discord_send_intent(self, *, intent_id: str, platform_message_id: str) -> bool:
        """Transition a pending intent to 'resolved' with its recovered platform id.

        Returns False when the intent is missing or already terminal —
        callers must not retry a terminal disposition into a different one.
        """
        now = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            row = await db_session.get(db_models.DiscordSendIntentRow, intent_id)
            if row is None or row.status in _TERMINAL_INTENT_STATUSES:
                return False
            row.status = DiscordSendIntentStatus.RESOLVED
            row.platform_message_id = platform_message_id
            row.resolved_at = now
            db_session.add(row)
            await db_session.commit()
            return True

    async def omit_discord_send_intent(self, *, intent_id: str) -> bool:
        """Close an intent as 'omitted': inconclusive reconciliation, lane released, never resent."""
        now = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            row = await db_session.get(db_models.DiscordSendIntentRow, intent_id)
            if row is None or row.status in _TERMINAL_INTENT_STATUSES:
                return False
            row.status = DiscordSendIntentStatus.OMITTED
            row.resolved_at = now
            db_session.add(row)
            await db_session.commit()
            return True

    async def replay_discord_send_intent(
        self,
        *,
        omitted_intent_id: str,
        new_intent_id: str,
        generation_id: str,
        channel_id: str,
    ) -> DiscordSendIntent | None:
        """Mark an omitted intent 'replayed' and open a fresh pending retry intent.

        Returns the new pending intent, or ``None`` when the source intent is
        missing or not currently 'omitted'.
        """
        now = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            omitted = await db_session.get(db_models.DiscordSendIntentRow, omitted_intent_id)
            if omitted is None or omitted.status != DiscordSendIntentStatus.OMITTED:
                return None
            omitted.status = DiscordSendIntentStatus.REPLAYED
            db_session.add(omitted)
            new_row = db_models.DiscordSendIntentRow(
                intent_id=new_intent_id,
                session_id=omitted.session_id,
                generation_id=generation_id,
                channel_id=channel_id,
                status=DiscordSendIntentStatus.PENDING,
                replays_intent_id=omitted_intent_id,
                created_at=now,
            )
            db_session.add(new_row)
            await db_session.commit()
            return _decode_intent(new_row)

    async def prune_output_state(self, *, cutoff_iso: str, retained_session_ids: set[str]) -> tuple[int, int, int, int]:
        """Delete output state that no live consumer can still read, older than the cutoff.

        Terminal Discord send intents go first, then receipts and generations other than a retained
        session's latest, then the cursors of sessions no longer retained. A generation a pending intent
        references stays. Returns the rows removed from intents, receipts, generations and cursors, in that
        order.
        """
        intents = db_models.DiscordSendIntentRow
        receipts = db_models.OutputConsumerReceiptRow
        generations = db_models.OutputGenerationRow
        cursors = db_models.OutputConsumerCursorRow

        # The latest generation per session, by the order get_latest_output_generation reads.
        sibling = aliased(generations)
        latest_of_receipt_session = (
            select(sibling.generation_id)
            .where(sibling.session_id == receipts.session_id)
            .order_by(sibling.created_at.desc())  # type: ignore[attr-defined]
            .limit(1)
            .scalar_subquery()
        )
        latest_of_generation_session = (
            select(sibling.generation_id)
            .where(sibling.session_id == generations.session_id)
            .order_by(sibling.created_at.desc())  # type: ignore[attr-defined]
            .limit(1)
            .scalar_subquery()
        )
        statements = (
            delete(intents).where(
                intents.status.in_(_TERMINAL_INTENT_STATUSES),  # type: ignore[attr-defined]
                func.coalesce(intents.resolved_at, intents.created_at) < cutoff_iso,
            ),
            delete(receipts).where(
                receipts.updated_at < cutoff_iso,
                or_(
                    receipts.session_id.notin_(retained_session_ids),  # type: ignore[attr-defined]
                    receipts.generation_id != latest_of_receipt_session,
                ),
            ),
            delete(generations).where(
                generations.created_at < cutoff_iso,
                or_(
                    generations.session_id.notin_(retained_session_ids),  # type: ignore[attr-defined]
                    generations.generation_id != latest_of_generation_session,
                ),
                ~exists().where(
                    intents.generation_id == generations.generation_id,
                    intents.status == DiscordSendIntentStatus.PENDING,
                ),
            ),
            delete(cursors).where(
                cursors.session_id.notin_(retained_session_ids),  # type: ignore[attr-defined]
                cursors.updated_at < cutoff_iso,
            ),
        )
        async with self._store_session(DaemonStore.OUTPUT) as db_session:
            removed = tuple([(await db_session.exec(statement)).rowcount or 0 for statement in statements])
            await db_session.commit()
        intents_removed, receipts_removed, generations_removed, cursors_removed = removed
        return intents_removed, receipts_removed, generations_removed, cursors_removed
