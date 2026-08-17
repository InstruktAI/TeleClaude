"""Serialized reminder mutations and daemon-owned scheduling."""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from .models import (
    PrescribedReminderSlug,
    Reminder,
    ReminderEntry,
    ReminderEvent,
    ReminderRecurrence,
    ReminderSetRequest,
)
from .observability import (
    observe_advanced,
    observe_cancel,
    observe_clear,
    observe_event_match,
    observe_query,
    observe_reconciliation,
    observe_transition,
)
from .profiles import PrescribedReminderInput, format_prescribed_reminder

if TYPE_CHECKING:
    from teleclaude.core.db import Db

logger = get_logger(__name__)

ReminderSubmitter = Callable[[ReminderEntry], Awaitable[bool]]
ReminderProjectionNotifier = Callable[[str], Awaitable[None]]

_SCHEDULER_FAILURE_EVENT = "reminder_scheduler_iteration_failed"
_SUBMITTER_REQUIRED = "reminder firing requires an input submitter"
_RESERVED_SLUG_ERROR = "reserved reminder slugs require their prescribed profile surface"
_PROFILE_SLUG_ERROR = "prescribed reminder profile and slug must match"
_RETRY_SECONDS = 1.0


async def _noop_projection_notifier(session_id: str) -> None:
    _ = session_id


def _event_matches(reminder: Reminder, event: ReminderEvent) -> bool:
    return reminder.schedule.event_anchor is event.anchor


class ReminderService:
    """Single mutation gate and scheduler facade for reminder aggregates."""

    def __init__(
        self,
        database: Db,
        *,
        submitter: ReminderSubmitter | None = None,
        projection_notifier: ReminderProjectionNotifier = _noop_projection_notifier,
    ) -> None:
        self._db = database
        self._submitter = submitter
        self._projection_notifier = projection_notifier
        self._mutation_lock = asyncio.Lock()
        self._wake = asyncio.Event()

    def set_submitter(self, submitter: ReminderSubmitter) -> None:
        """Install the existing-input adapter during daemon composition."""
        self._submitter = submitter

    def set_projection_notifier(self, notifier: ReminderProjectionNotifier) -> None:
        """Install the existing session-projection wake seam."""
        self._projection_notifier = notifier

    async def set(self, request: ReminderSetRequest) -> ReminderEntry:
        """Arm or atomically replace one reminder generation."""
        prescribed = _prescribed_slug(request.slug)
        if prescribed is not None and request.profile is None:
            raise ValueError(_RESERVED_SLUG_ERROR)
        if request.profile is not None and request.profile.value != request.slug:
            raise ValueError(_PROFILE_SLUG_ERROR)
        async with self._mutation_lock:
            _, entry = await self._db.set_reminder(request)
        observe_transition(entry)
        await self._projection_notifier(entry.session_id)
        self._wake.set()
        return entry

    async def set_prescribed(
        self,
        *,
        session_id: str,
        slug: PrescribedReminderSlug,
        inputs: PrescribedReminderInput,
    ) -> ReminderEntry:
        """Resolve and set one registered prescribed reminder."""
        request = format_prescribed_reminder(session_id=session_id, slug=slug, inputs=inputs)
        return await self.set(request)

    async def list(self, *, session_id: str) -> builtins.list[Reminder]:
        """List every live reminder owned by the authenticated caller session."""
        reminders = await self._db.list_reminders(session_id=session_id)
        observe_query(session_id, reminders=reminders)
        return reminders

    async def next_scheduled(self, *, session_id: str) -> Reminder | None:
        """Return the caller's earliest concrete reminder."""
        return await self._db.get_next_scheduled_reminder(session_id=session_id)

    async def cancel(self, *, session_id: str, slug: str) -> ReminderEntry | None:
        """Idempotently cancel one caller-owned reminder."""
        transaction_id = str(uuid4())
        async with self._mutation_lock:
            entry = await self._db.cancel_reminder(session_id=session_id, slug=slug)
        observe_cancel(
            session_id,
            slug=slug,
            entries=[entry] if entry is not None else [],
            transaction_id=transaction_id,
        )
        if entry is not None:
            observe_transition(entry)
            await self._projection_notifier(session_id)
            self._wake.set()
        return entry

    async def cancel_all(self, *, session_id: str) -> builtins.list[ReminderEntry]:
        """Idempotently cancel every caller-owned reminder in one transaction."""
        transaction_id = str(uuid4())
        async with self._mutation_lock:
            entries = await self._db.cancel_all_reminders(session_id=session_id, append_entries=True)
        observe_cancel(session_id, slug=None, entries=entries, transaction_id=transaction_id)
        for entry in entries:
            observe_transition(entry)
        if entries:
            await self._projection_notifier(session_id)
            self._wake.set()
        return entries

    async def clear_session(self, *, session_id: str, operation_id: str) -> int:
        """Clear ended-session state without appending transcript source entries."""
        async with self._mutation_lock:
            reminders = await self._db.list_reminders(session_id=session_id)
            await self._db.cancel_all_reminders(session_id=session_id, append_entries=False)
        observe_clear(session_id, count=len(reminders), operation_id=operation_id)
        self._wake.set()
        return len(reminders)

    async def handle_agent_event(self, event: ReminderEvent) -> int:
        """Evaluate typed predicates and directly fire every matching anchor."""
        reminders = await self._db.list_event_reminders(session_id=event.session_id)
        fired = 0
        for reminder in reminders:
            matched = _event_matches(reminder, event)
            observe_event_match(event, reminder, matched=matched)
            if not matched:
                continue
            entry = await self._fire(reminder, fired_at=datetime.now(UTC))
            fired += int(entry is not None)
        return fired

    async def reconcile(self) -> None:
        """Record current future/overdue counts before the scheduler starts."""
        now = datetime.now(UTC)
        due = await self._db.list_due_reminders(at=now)
        claimed = await self._db.list_claimed_reminders()
        scheduled = await self._db.list_scheduled_reminders()
        future_count = sum(
            reminder.schedule.next_fire_at is not None and reminder.schedule.next_fire_at > now
            for reminder in scheduled
        )
        observe_reconciliation(future_count=future_count, overdue_count=len(due) + len(claimed))

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Run one wakeable durable scheduler until daemon shutdown."""
        await self.reconcile()
        while not shutdown_event.is_set():
            try:
                await self._run_scheduler_iteration(shutdown_event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(_SCHEDULER_FAILURE_EVENT, error=str(exc))
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_RETRY_SECONDS)
                except TimeoutError:
                    continue

    async def _run_scheduler_iteration(self, shutdown_event: asyncio.Event) -> None:
        now = datetime.now(UTC)
        claimed = await self._db.list_claimed_reminders()
        retry_before = now - timedelta(seconds=_RETRY_SECONDS)
        for reminder in claimed:
            if reminder.claimed_at is not None and reminder.claimed_at <= retry_before:
                await self._fire(reminder, fired_at=now)
        due = await self._db.list_due_reminders(at=now)
        for reminder in due:
            await self._fire(reminder, fired_at=now)
        deadlines = await self._scheduler_deadlines()
        if not deadlines:
            await self._wait_for_wake_or_shutdown(shutdown_event, timeout=None)
            return
        delay = max((min(deadlines) - datetime.now(UTC)).total_seconds(), 0.0)
        await self._wait_for_wake_or_shutdown(shutdown_event, timeout=delay)

    async def _scheduler_deadlines(self) -> builtins.list[datetime]:
        scheduled = await self._db.list_scheduled_reminders()
        claimed = await self._db.list_claimed_reminders()
        deadlines = [
            reminder.schedule.next_fire_at
            for reminder in scheduled
            if reminder.claimed_occurrence_key is None and reminder.schedule.next_fire_at is not None
        ]
        deadlines.extend(
            reminder.claimed_at + timedelta(seconds=_RETRY_SECONDS)
            for reminder in claimed
            if reminder.claimed_at is not None
        )
        return deadlines

    async def _wait_for_wake_or_shutdown(self, shutdown_event: asyncio.Event, *, timeout: float | None) -> None:
        self._wake.clear()
        wake_task = asyncio.create_task(self._wake.wait())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        tasks = {wake_task, shutdown_task}
        try:
            await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _fire(self, reminder: Reminder, *, fired_at: datetime) -> ReminderEntry | None:
        if self._submitter is None:
            raise RuntimeError(_SUBMITTER_REQUIRED)
        async with self._mutation_lock:
            entry = await self._db.claim_reminder_occurrence(
                session_id=reminder.session_id,
                slug=reminder.slug,
                generation=reminder.generation,
                occurrence_key=reminder.occurrence_key,
                fired_at=fired_at,
            )
            if entry is None:
                return None
            self._wake.set()
            observe_transition(entry)
            await self._projection_notifier(entry.session_id)
            try:
                accepted = await self._submitter(entry)
            except Exception:
                self._wake.set()
                raise
            if not accepted:
                self._wake.set()
                return None
            advanced = await self._db.accept_reminder_occurrence(entry)
        if advanced is not None and advanced.schedule.recurrence is ReminderRecurrence.RECURRING:
            observe_advanced(advanced)
        self._wake.set()
        return entry


def _prescribed_slug(value: str) -> PrescribedReminderSlug | None:
    try:
        return PrescribedReminderSlug(value)
    except ValueError:
        return None
