"""Mixin: durable reminder aggregates and append-only source entries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete
from sqlmodel import select

from .. import db_models
from ..dates import ensure_utc
from ..reminders.models import (
    PrescribedReminderSlug,
    Reminder,
    ReminderEntry,
    ReminderEntryReadFailure,
    ReminderEntryReadItem,
    ReminderEventAnchor,
    ReminderRecurrence,
    ReminderSchedule,
    ReminderSetRequest,
    ReminderTransition,
    ReminderTrigger,
)
from ..reminders.observability import observe_entry_read_failure
from .stores import DaemonStore

_CLAIMED_ENTRY_MISSING = "claimed reminder occurrence is missing its firing entry"


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _decode_schedule(row: db_models.ReminderRow | db_models.ReminderEntryRow) -> ReminderSchedule:
    return ReminderSchedule(
        trigger=ReminderTrigger(row.trigger_type),
        recurrence=ReminderRecurrence(row.recurrence),
        next_fire_at=_parse_datetime(row.next_fire_at),
        interval_seconds=row.interval_seconds,
        event_anchor=ReminderEventAnchor(row.event_anchor) if row.event_anchor is not None else None,
    )


def _decode_reminder(row: db_models.ReminderRow) -> Reminder:
    armed_at = _parse_datetime(row.armed_at)
    if armed_at is None:
        raise ValueError("reminder row is missing armed_at")
    return Reminder(
        session_id=row.session_id,
        slug=row.slug,
        profile=PrescribedReminderSlug(row.profile) if row.profile is not None else None,
        intent=row.intent,
        schedule=_decode_schedule(row),
        armed_at=armed_at,
        generation=row.generation,
        occurrence_key=row.occurrence_key,
        firing_count=row.firing_count,
        sliding=row.sliding,
        claimed_occurrence_key=row.claimed_occurrence_key,
        claimed_at=_parse_datetime(row.claimed_at),
    )


def _decode_entry(row: db_models.ReminderEntryRow) -> ReminderEntry:
    armed_at = _parse_datetime(row.armed_at)
    occurred_at = _parse_datetime(row.occurred_at)
    if armed_at is None or occurred_at is None or row.entry_id is None:
        raise ValueError("reminder entry row is incomplete")
    return ReminderEntry(
        entry_id=row.entry_id,
        session_id=row.session_id,
        slug=row.slug,
        generation=row.generation,
        transition=ReminderTransition(row.transition),
        profile=row.profile,
        intent=row.intent,
        schedule=_decode_schedule(row),
        armed_at=armed_at,
        occurred_at=occurred_at,
        occurrence_key=row.occurrence_key,
        sliding=row.sliding,
        firing_number=row.firing_number,
    )


def _new_reminder_row(request: ReminderSetRequest, *, generation: int, armed_at: datetime) -> db_models.ReminderRow:
    schedule = request.schedule
    return db_models.ReminderRow(
        session_id=request.session_id,
        slug=request.slug,
        profile=request.profile.value if request.profile is not None else None,
        intent=request.intent,
        trigger_type=schedule.trigger.value,
        event_anchor=schedule.event_anchor.value if schedule.event_anchor is not None else None,
        recurrence=schedule.recurrence.value,
        interval_seconds=schedule.interval_seconds,
        armed_at=armed_at.isoformat(),
        next_fire_at=schedule.next_fire_at.isoformat() if schedule.next_fire_at is not None else None,
        generation=generation,
        occurrence_key=str(uuid4()),
        firing_count=0,
        sliding=request.sliding,
    )


def _entry_row(
    reminder: db_models.ReminderRow,
    *,
    transition: ReminderTransition,
    occurred_at: datetime,
    next_fire_at: datetime | None = None,
    firing_number: int | None = None,
) -> db_models.ReminderEntryRow:
    return db_models.ReminderEntryRow(
        session_id=reminder.session_id,
        slug=reminder.slug,
        generation=reminder.generation,
        transition=transition.value,
        profile=reminder.profile,
        intent=reminder.intent,
        trigger_type=reminder.trigger_type,
        event_anchor=reminder.event_anchor,
        recurrence=reminder.recurrence,
        interval_seconds=reminder.interval_seconds,
        armed_at=reminder.armed_at,
        occurred_at=occurred_at.isoformat(),
        next_fire_at=(next_fire_at if next_fire_at is not None else _parse_datetime(reminder.next_fire_at)).isoformat()
        if (next_fire_at is not None or reminder.next_fire_at is not None)
        else None,
        occurrence_key=reminder.occurrence_key,
        sliding=reminder.sliding,
        firing_number=firing_number,
    )


class DbRemindersMixin:
    """Reminder aggregate persistence owned by the agent-runtime context."""

    async def set_reminder(self, request: ReminderSetRequest) -> tuple[Reminder, ReminderEntry]:
        """Atomically arm or replace one session-local slug generation."""
        now = datetime.now(UTC)
        key = {"session_id": request.session_id, "slug": request.slug}
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            existing = await db_session.get(db_models.ReminderRow, key)
            generation = existing.generation + 1 if existing is not None else 1
            transition = ReminderTransition.REPLACED if existing is not None else ReminderTransition.ARMED
            if existing is not None:
                await db_session.delete(existing)
                await db_session.flush()
            row = _new_reminder_row(request, generation=generation, armed_at=now)
            entry_row = _entry_row(row, transition=transition, occurred_at=now)
            db_session.add(row)
            db_session.add(entry_row)
            await db_session.commit()
            await db_session.refresh(entry_row)
            return _decode_reminder(row), _decode_entry(entry_row)

    async def get_reminder(self, *, session_id: str, slug: str) -> Reminder | None:
        """Return one caller-owned reminder aggregate."""
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            row = await db_session.get(db_models.ReminderRow, {"session_id": session_id, "slug": slug})
            return _decode_reminder(row) if row is not None else None

    async def list_reminders(self, *, session_id: str) -> list[Reminder]:
        """Return every live reminder for one owning session."""
        statement = (
            select(db_models.ReminderRow)
            .where(db_models.ReminderRow.session_id == session_id)
            .order_by(db_models.ReminderRow.slug)  # type: ignore[arg-type]
        )
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_reminder(row) for row in rows]

    async def list_due_reminders(self, *, at: datetime) -> list[Reminder]:
        """Return unclaimed concrete occurrences due by the supplied instant."""
        statement = (
            select(db_models.ReminderRow)
            .where(db_models.ReminderRow.next_fire_at.is_not(None))
            .where(db_models.ReminderRow.claimed_occurrence_key.is_(None))
            .where(db_models.ReminderRow.next_fire_at <= ensure_utc(at).isoformat())
            .order_by(db_models.ReminderRow.next_fire_at)  # type: ignore[arg-type]
        )
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_reminder(row) for row in rows]

    async def list_claimed_reminders(self) -> list[Reminder]:
        """Return claimed occurrences ordered by their latest submission attempt."""
        statement = (
            select(db_models.ReminderRow)
            .where(db_models.ReminderRow.claimed_occurrence_key.is_not(None))
            .order_by(db_models.ReminderRow.claimed_at)  # type: ignore[arg-type]
        )
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_reminder(row) for row in rows]

    async def list_scheduled_reminders(self) -> list[Reminder]:
        """Return every concrete aggregate for startup reconciliation."""
        statement = (
            select(db_models.ReminderRow)
            .where(db_models.ReminderRow.next_fire_at.is_not(None))
            .order_by(db_models.ReminderRow.next_fire_at)  # type: ignore[arg-type]
        )
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_reminder(row) for row in rows]

    async def get_next_scheduled_reminder(self, *, session_id: str | None = None) -> Reminder | None:
        """Return the earliest concrete live reminder, optionally for one owner."""
        statement = select(db_models.ReminderRow).where(db_models.ReminderRow.next_fire_at.is_not(None))
        if session_id is not None:
            statement = statement.where(db_models.ReminderRow.session_id == session_id)
        statement = statement.order_by(db_models.ReminderRow.next_fire_at).limit(1)  # type: ignore[arg-type]
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            row = (await db_session.exec(statement)).first()
            return _decode_reminder(row) if row is not None else None

    async def list_event_reminders(
        self, *, session_id: str, anchor: ReminderEventAnchor | None = None
    ) -> list[Reminder]:
        """Return live event-anchored reminders for one owning session."""
        statement = (
            select(db_models.ReminderRow)
            .where(db_models.ReminderRow.session_id == session_id)
            .where(db_models.ReminderRow.event_anchor.is_not(None))
            .where(db_models.ReminderRow.claimed_occurrence_key.is_(None))
        )
        if anchor is not None:
            statement = statement.where(db_models.ReminderRow.event_anchor == anchor.value)
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = (await db_session.exec(statement)).all()
            return [_decode_reminder(row) for row in rows]

    async def cancel_reminder(self, *, session_id: str, slug: str) -> ReminderEntry | None:
        """Atomically remove one live aggregate and append its cancellation entry."""
        now = datetime.now(UTC)
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            row = await db_session.get(db_models.ReminderRow, {"session_id": session_id, "slug": slug})
            if row is None:
                return None
            entry_row = _entry_row(row, transition=ReminderTransition.CANCELLED, occurred_at=now)
            db_session.add(entry_row)
            await db_session.delete(row)
            await db_session.commit()
            await db_session.refresh(entry_row)
            return _decode_entry(entry_row)

    async def cancel_all_reminders(self, *, session_id: str, append_entries: bool) -> list[ReminderEntry]:
        """Remove every live aggregate for one session in one transaction."""
        now = datetime.now(UTC)
        statement = select(db_models.ReminderRow).where(db_models.ReminderRow.session_id == session_id)
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = list((await db_session.exec(statement)).all())
            entry_rows = (
                [_entry_row(row, transition=ReminderTransition.CANCELLED, occurred_at=now) for row in rows]
                if append_entries
                else []
            )
            for entry_row in entry_rows:
                db_session.add(entry_row)
            await db_session.exec(delete(db_models.ReminderRow).where(db_models.ReminderRow.session_id == session_id))
            await db_session.commit()
            for entry_row in entry_rows:
                await db_session.refresh(entry_row)
            return [_decode_entry(entry_row) for entry_row in entry_rows]

    async def claim_reminder_occurrence(
        self, *, session_id: str, slug: str, generation: int, occurrence_key: str, fired_at: datetime
    ) -> ReminderEntry | None:
        """Claim the current occurrence and append its unique firing entry."""
        key = {"session_id": session_id, "slug": slug}
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            row = await db_session.get(db_models.ReminderRow, key)
            if row is None or row.generation != generation or row.occurrence_key != occurrence_key:
                return None
            if row.claimed_occurrence_key is not None:
                statement = select(db_models.ReminderEntryRow).where(
                    db_models.ReminderEntryRow.occurrence_key == occurrence_key,
                    db_models.ReminderEntryRow.transition == ReminderTransition.FIRING.value,
                )
                existing = (await db_session.exec(statement)).first()
                if existing is None:
                    raise RuntimeError(_CLAIMED_ENTRY_MISSING)
                row.claimed_at = ensure_utc(fired_at).isoformat()
                db_session.add(row)
                await db_session.commit()
                return _decode_entry(existing)
            row.claimed_occurrence_key = occurrence_key
            row.claimed_at = ensure_utc(fired_at).isoformat()
            row.firing_count += 1
            next_fire_at = None
            if row.recurrence == ReminderRecurrence.RECURRING.value:
                if row.interval_seconds is None:
                    raise ValueError("recurring reminder row is missing interval_seconds")
                next_fire_at = ensure_utc(fired_at) + timedelta(seconds=row.interval_seconds)
            entry_row = _entry_row(
                row,
                transition=ReminderTransition.FIRING,
                occurred_at=ensure_utc(fired_at),
                next_fire_at=next_fire_at,
                firing_number=row.firing_count,
            )
            db_session.add(row)
            db_session.add(entry_row)
            await db_session.commit()
            await db_session.refresh(entry_row)
            return _decode_entry(entry_row)

    async def accept_reminder_occurrence(self, entry: ReminderEntry) -> Reminder | None:
        """Consume a one-shot or advance a recurring occurrence after acceptance."""
        key = {"session_id": entry.session_id, "slug": entry.slug}
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            row = await db_session.get(db_models.ReminderRow, key)
            if row is None or row.occurrence_key != entry.occurrence_key:
                return None
            if row.recurrence == ReminderRecurrence.ONE_SHOT.value:
                await db_session.delete(row)
                await db_session.commit()
                return None
            if entry.schedule.next_fire_at is None:
                raise ValueError("recurring firing entry is missing next_fire_at")
            row.next_fire_at = entry.schedule.next_fire_at.isoformat()
            row.occurrence_key = str(uuid4())
            row.claimed_occurrence_key = None
            row.claimed_at = None
            db_session.add(row)
            await db_session.commit()
            return _decode_reminder(row)

    async def slide_reminder_occurrence(
        self,
        *,
        session_id: str,
        slug: str,
        generation: int,
        occurrence_key: str,
        next_fire_at: datetime,
    ) -> Reminder | None:
        """Re-anchor one unclaimed sliding occurrence without advancing it."""
        key = {"session_id": session_id, "slug": slug}
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            row = await db_session.get(db_models.ReminderRow, key)
            if (
                row is None
                or row.generation != generation
                or row.occurrence_key != occurrence_key
                or row.claimed_occurrence_key is not None
            ):
                return None
            row.next_fire_at = ensure_utc(next_fire_at).isoformat()
            db_session.add(row)
            await db_session.commit()
            return _decode_reminder(row)

    async def list_reminder_entries(self, *, session_id: str, after_entry_id: int = 0) -> list[ReminderEntryReadItem]:
        """Return append-only reminder entries after one consumer cursor."""
        statement = (
            select(db_models.ReminderEntryRow)
            .where(db_models.ReminderEntryRow.session_id == session_id)
            .where(db_models.ReminderEntryRow.entry_id > after_entry_id)
            .order_by(db_models.ReminderEntryRow.entry_id)  # type: ignore[arg-type]
        )
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            rows = (await db_session.exec(statement)).all()
            entries: list[ReminderEntryReadItem] = []
            for row in rows:
                if row.entry_id is None:
                    raise ValueError("reminder entry row is missing entry_id")
                try:
                    entries.append(_decode_entry(row))
                except (TypeError, ValueError) as exc:
                    try:
                        occurred_at = _parse_datetime(row.occurred_at)
                    except (TypeError, ValueError):
                        occurred_at = None
                    failure = ReminderEntryReadFailure(
                        entry_id=row.entry_id,
                        session_id=row.session_id,
                        occurred_at=occurred_at,
                        reason=type(exc).__name__,
                    )
                    observe_entry_read_failure(failure)
                    entries.append(failure)
            return entries

    async def prune_reminder_entries(self, *, cutoff_iso: str, retained_session_ids: set[str]) -> int:
        """Delete reminder entries older than the cutoff whose session is no longer retained.

        An entry whose occurrence key a live or claimed reminder still carries stays: the claim looks its
        firing entry up by that key.
        """
        entries = db_models.ReminderEntryRow
        reminders = db_models.ReminderRow
        statement = delete(entries).where(
            entries.occurred_at < cutoff_iso,
            entries.session_id.notin_(retained_session_ids),  # type: ignore[attr-defined]
            entries.occurrence_key.notin_(select(reminders.occurrence_key)),  # type: ignore[attr-defined]
            entries.occurrence_key.notin_(  # type: ignore[attr-defined]
                select(reminders.claimed_occurrence_key).where(reminders.claimed_occurrence_key.is_not(None))
            ),
        )
        async with self._store_session(DaemonStore.REMINDERS) as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
            return result.rowcount or 0
