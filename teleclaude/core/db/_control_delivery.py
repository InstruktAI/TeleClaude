"""Persistence owned by the control-delivery bounded context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from teleclaude.core import db_models
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.models import Session
from teleclaude.core.session_status import AgentStatusValue, is_agent_turn_running
from teleclaude.docs_subscriptions import EventDeliveryMode, SubscriptionAttendance, SubscriptionIdentity
from teleclaude.types.procedure_delivery import ProcedureSessionDeliveryInitialization

_PROCEDURE_EVENT_MISSING_ERROR = "initial procedure event was not accepted before session creation"
_PROCEDURE_ACTIVATION_REPLAY_CONFLICT = "procedure activation identity was reused with different accepted facts"
_PROCEDURE_ACTIVATION_IDENTITY_REQUIRED = "procedure activation requires an identity"


@dataclass(frozen=True)
class ControlDeliveryRecord:
    """One selected control payload, ordered by durable row identity."""

    id: int
    session_id: str
    envelope_name: str | None
    envelope_fields_json: str | None
    body: str
    body_digest: str
    created_at: str
    outcome: db_models.ControlDeliveryOutcome | None
    terminal_at: str | None


def _record(row: db_models.ControlDelivery) -> ControlDeliveryRecord:
    """Decode the persisted row into the context's published record."""
    if row.id is None:
        raise RuntimeError("control_outbox row has no durable id")
    outcome = db_models.ControlDeliveryOutcome(row.outcome) if row.outcome is not None else None
    return ControlDeliveryRecord(
        id=row.id,
        session_id=row.session_id,
        envelope_name=row.envelope_name,
        envelope_fields_json=row.envelope_fields_json,
        body=row.body,
        body_digest=row.body_digest,
        created_at=row.created_at,
        outcome=outcome,
        terminal_at=row.terminal_at,
    )


@dataclass(frozen=True)
class ProcedureEventRecord:
    """One activation retained by its procedure responsibility identity."""

    enqueue_order: int
    activation_id: str
    responsibility_key: str
    procedure_id: str
    home: str
    subject: str | None
    event_json: str
    identity: SubscriptionIdentity
    attendance: SubscriptionAttendance
    event_delivery: EventDeliveryMode
    interruptible: bool
    assigned_session_id: str | None
    outcome: db_models.ProcedureEventDeliveryOutcome
    outcome_reason: str | None
    accepted_at: str
    terminal_at: str | None


@dataclass(frozen=True)
class ProcedureDeliverySessionRecord:
    """The delivery policy a procedure session was initialized with, and the responsibility it carries."""

    procedure_id: str
    responsibility_key: str
    event_delivery: EventDeliveryMode
    interruptible: bool


def _procedure_event_record(row: db_models.ProcedureEventInbox) -> ProcedureEventRecord:
    if row.enqueue_order is None:
        raise RuntimeError("procedure event has no durable enqueue order")
    return ProcedureEventRecord(
        enqueue_order=row.enqueue_order,
        activation_id=row.activation_id,
        responsibility_key=row.responsibility_key,
        procedure_id=row.procedure_id,
        home=row.home,
        subject=row.subject,
        event_json=row.event_json,
        identity=SubscriptionIdentity(row.identity),
        attendance=SubscriptionAttendance(row.attendance),
        event_delivery=EventDeliveryMode(row.event_delivery),
        interruptible=row.interruptible,
        assigned_session_id=row.assigned_session_id,
        outcome=db_models.ProcedureEventDeliveryOutcome(row.outcome),
        outcome_reason=row.outcome_reason,
        accepted_at=row.accepted_at,
        terminal_at=row.terminal_at,
    )


async def initialize_procedure_delivery_in_transaction(
    db_session: AsyncSession,
    *,
    session_id: str,
    initialized_at: str,
    delivery: ProcedureSessionDeliveryInitialization,
) -> None:
    """Bind initial responsibility state and event before session bootstrap can start."""
    await db_session.flush()
    db_session.add(
        db_models.ProcedureEventDeliverySession(
            session_id=session_id,
            procedure_id=delivery.procedure_id,
            responsibility_key=delivery.responsibility_key,
            event_delivery=delivery.event_delivery.value,
            interruptible=delivery.interruptible,
            initialized_at=initialized_at,
            initial_entry_id=delivery.initial_entry_id,
        )
    )
    assignment = await db_session.exec(
        update(db_models.ProcedureEventInbox)
        .where(db_models.ProcedureEventInbox.activation_id.in_(delivery.activation_ids))
        .where(
            db_models.ProcedureEventInbox.outcome.in_(
                [
                    db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                    db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                ]
            )
        )
        .values(
            assigned_session_id=session_id,
            outcome=db_models.ProcedureEventDeliveryOutcome.PENDING.value,
            outcome_reason=None,
        )
    )
    if assignment.rowcount != len(delivery.activation_ids):
        raise RuntimeError(_PROCEDURE_EVENT_MISSING_ERROR)


def _envelope_fields_match(envelope_fields_json: str | None, key_fields: dict[str, str]) -> bool:
    """Return whether a stored envelope carries every declared key field."""
    if envelope_fields_json is None:
        return False
    decoded = json.loads(envelope_fields_json)
    return all(decoded.get(field) == value for field, value in key_fields.items())


class DbControlDeliveryMixin:
    """Public persistence seam for producer handoff, drain, and close cleanup."""

    async def prune_control_delivery(self, *, cutoff_iso: str, retained_session_ids: set[str]) -> tuple[int, int]:
        """Delete control payloads and procedure events whose work is over and older than the cutoff.

        Terminal control payloads and failed procedure events go once past the cutoff. A delivered
        procedure event can still be unfinished work for its assigned session, so it goes only when that
        session is no longer retained. Returns the rows removed from each table, in that order.
        """
        outbox_stmt = delete(db_models.ControlDelivery).where(
            db_models.ControlDelivery.outcome.is_not(None),
            db_models.ControlDelivery.terminal_at < cutoff_iso,
        )
        assigned = db_models.ProcedureEventInbox.assigned_session_id
        events_stmt = delete(db_models.ProcedureEventInbox).where(
            db_models.ProcedureEventInbox.terminal_at < cutoff_iso,
            or_(
                db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.FAILED.value,
                and_(
                    db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.DELIVERED.value,
                    or_(assigned.is_(None), assigned.notin_(retained_session_ids)),
                ),
            ),
        )
        async with self._session() as db_session:
            outbox_result = await db_session.exec(outbox_stmt)
            events_result = await db_session.exec(events_stmt)
            await db_session.commit()
            return outbox_result.rowcount or 0, events_result.rowcount or 0

    async def prepare_procedure_event_wake_opportunity(self, *, session_id: str) -> str | None:
        """Create or reuse a correlated wake opportunity for pending assigned events."""
        async with self._session() as db_session:
            state = (
                await db_session.exec(
                    select(db_models.ProcedureEventDeliverySession).where(
                        db_models.ProcedureEventDeliverySession.session_id == session_id
                    )
                )
            ).first()
            pending = (
                await db_session.exec(
                    select(db_models.ProcedureEventInbox)
                    .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
                    .where(
                        db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value
                    )
                    .order_by(db_models.ProcedureEventInbox.enqueue_order.asc())
                )
            ).first()
            if pending is None:
                return None
            if state is not None and state.initial_entry_id is not None and state.initial_entry_consumed_at is None:
                return None
            if state is not None and state.wake_occurrence_id is not None:
                return state.wake_occurrence_id
            inbound_max = (
                await db_session.exec(
                    select(func.max(db_models.InboundQueue.id)).where(db_models.InboundQueue.session_id == session_id)
                )
            ).one()
            occurrence_id = uuid4().hex
            if state is None:
                state = db_models.ProcedureEventDeliverySession(
                    session_id=session_id,
                    procedure_id=pending.procedure_id,
                    responsibility_key=pending.responsibility_key,
                    event_delivery=pending.event_delivery,
                    interruptible=pending.interruptible,
                    initialized_at=datetime.now(UTC).isoformat(),
                )
            state.wake_occurrence_id = occurrence_id
            state.wake_accepted_occurrence_id = None
            state.wake_observed_last_input_at = None
            state.wake_observed_last_agent_stop_at = None
            state.wake_observed_last_agent_idle_at = None
            state.wake_observed_inbound_id = inbound_max
            db_session.add(state)
            await db_session.commit()
        return occurrence_id

    async def reassign_procedure_events(self, *, responsibility_key: str, session_id: str) -> int:
        """Reconcile pending and suspended responsibility work to its resolved session."""
        statement = (
            update(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.responsibility_key == responsibility_key)
            .where(
                db_models.ProcedureEventInbox.outcome.in_(
                    [
                        db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                        db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                    ]
                )
            )
            .values(
                assigned_session_id=session_id,
                outcome=db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                outcome_reason=None,
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        return result.rowcount or 0

    async def suspend_procedure_events_for_session(self, *, session_id: str, reason: str) -> int:
        """Retain assigned work as suspended when its current session closes."""
        async with self._session() as db_session:
            result = await db_session.exec(
                update(db_models.ProcedureEventInbox)
                .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
                .where(db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value)
                .values(
                    assigned_session_id=None,
                    outcome=db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                    outcome_reason=reason,
                )
            )
            await db_session.exec(
                update(db_models.ProcedureEventDeliverySession)
                .where(db_models.ProcedureEventDeliverySession.session_id == session_id)
                .values(
                    wake_occurrence_id=None,
                    wake_accepted_occurrence_id=None,
                    wake_observed_last_input_at=None,
                    wake_observed_last_agent_stop_at=None,
                    wake_observed_last_agent_idle_at=None,
                    wake_observed_inbound_id=None,
                )
            )
            await db_session.commit()
        return result.rowcount or 0

    async def count_pending_procedure_events_for_session(self, *, session_id: str) -> int:
        """Count responsibility work that still needs this session to continue."""
        async with self._session() as db_session:
            value = (
                await db_session.exec(
                    select(func.count())
                    .select_from(db_models.ProcedureEventInbox)
                    .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
                    .where(
                        db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value
                    )
                )
            ).one()
        return int(value)

    async def fail_procedure_responsibility_events(self, *, responsibility_key: str, reason: str) -> int:
        """Terminalize retained work when its responsibility cannot continue."""
        async with self._session() as db_session:
            result = await db_session.exec(
                update(db_models.ProcedureEventInbox)
                .where(db_models.ProcedureEventInbox.responsibility_key == responsibility_key)
                .where(
                    db_models.ProcedureEventInbox.outcome.in_(
                        [
                            db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                            db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                        ]
                    )
                )
                .values(
                    assigned_session_id=None,
                    outcome=db_models.ProcedureEventDeliveryOutcome.FAILED.value,
                    outcome_reason=reason,
                    terminal_at=datetime.now(UTC).isoformat(),
                )
            )
            await db_session.commit()
        return result.rowcount or 0

    async def fail_procedure_event(self, *, activation_id: str, reason: str) -> int:
        """Terminalize one activation that cannot meet its own accepted identity contract."""
        async with self._session() as db_session:
            result = await db_session.exec(
                update(db_models.ProcedureEventInbox)
                .where(db_models.ProcedureEventInbox.activation_id == activation_id)
                .where(
                    db_models.ProcedureEventInbox.outcome.in_(
                        [
                            db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                            db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                        ]
                    )
                )
                .values(
                    assigned_session_id=None,
                    outcome=db_models.ProcedureEventDeliveryOutcome.FAILED.value,
                    outcome_reason=reason,
                    terminal_at=datetime.now(UTC).isoformat(),
                )
            )
            await db_session.commit()
        return result.rowcount or 0

    async def remove_procedure_event_delivery_session(self, *, session_id: str) -> None:
        """Remove only session-scoped delivery state after the session row is purged."""
        async with self._session() as db_session:
            await db_session.exec(
                delete(db_models.ProcedureEventDeliverySession).where(
                    db_models.ProcedureEventDeliverySession.session_id == session_id
                )
            )
            await db_session.commit()

    async def latest_inbound_row_id(self, *, session_id: str) -> int | None:
        """Read the acceptance-order watermark used to reject a wake superseded by newer input."""
        async with self._session() as db_session:
            return (
                await db_session.exec(
                    select(func.max(db_models.InboundQueue.id)).where(db_models.InboundQueue.session_id == session_id)
                )
            ).one()

    async def record_procedure_event_wake_acceptance(
        self,
        *,
        session_id: str,
        occurrence_id: str | None,
        inbound_row_id: int,
        observed_inbound_id: int | None,
        observed_session: Session,
    ) -> None:
        """Correlate the newest accepted wake or invalidate one superseded by later input."""
        async with self._session() as db_session:
            state = (
                await db_session.exec(
                    select(db_models.ProcedureEventDeliverySession).where(
                        db_models.ProcedureEventDeliverySession.session_id == session_id
                    )
                )
            ).first()
            if state is None:
                pending = (
                    await db_session.exec(
                        select(db_models.ProcedureEventInbox)
                        .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
                        .where(
                            db_models.ProcedureEventInbox.outcome
                            == db_models.ProcedureEventDeliveryOutcome.PENDING.value
                        )
                        .order_by(db_models.ProcedureEventInbox.enqueue_order.asc())
                    )
                ).first()
                if pending is None or occurrence_id is None:
                    return
                state = db_models.ProcedureEventDeliverySession(
                    session_id=session_id,
                    procedure_id=pending.procedure_id,
                    responsibility_key=pending.responsibility_key,
                    event_delivery=pending.event_delivery,
                    interruptible=pending.interruptible,
                    initialized_at=datetime.now(UTC).isoformat(),
                    wake_observed_inbound_id=observed_inbound_id,
                )
            if state.initial_entry_id is not None and state.initial_entry_consumed_at is None:
                state.wake_occurrence_id = None
                state.wake_accepted_occurrence_id = None
                state.wake_observed_inbound_id = None
                db_session.add(state)
                await db_session.commit()
                return
            current_max = (
                await db_session.exec(
                    select(func.max(db_models.InboundQueue.id)).where(db_models.InboundQueue.session_id == session_id)
                )
            ).one()
            stale_predecessor = False
            opportunity_watermark = state.wake_observed_inbound_id
            if opportunity_watermark is None:
                opportunity_watermark = observed_inbound_id
            if occurrence_id is not None and opportunity_watermark is not None:
                predecessor = (
                    await db_session.exec(
                        select(func.count())
                        .select_from(db_models.InboundQueue)
                        .where(db_models.InboundQueue.session_id == session_id)
                        .where(db_models.InboundQueue.id > opportunity_watermark)
                        .where(db_models.InboundQueue.id < inbound_row_id)
                    )
                ).one()
                stale_predecessor = int(predecessor) > 0
            if (
                occurrence_id is not None
                and state.wake_accepted_occurrence_id is not None
                and state.wake_occurrence_id == state.wake_accepted_occurrence_id
                and state.wake_occurrence_id != occurrence_id
            ):
                await db_session.commit()
                return
            if occurrence_id is not None and current_max == inbound_row_id and not stale_predecessor:
                state.wake_occurrence_id = occurrence_id
                state.wake_accepted_occurrence_id = occurrence_id
                state.wake_observed_last_input_at = (
                    observed_session.last_message_sent_at.isoformat()
                    if observed_session.last_message_sent_at is not None
                    else None
                )
                state.wake_observed_last_agent_stop_at = (
                    observed_session.last_agent_stop_at.isoformat()
                    if observed_session.last_agent_stop_at is not None
                    else None
                )
                state.wake_observed_last_agent_idle_at = (
                    observed_session.last_agent_idle_at.isoformat()
                    if observed_session.last_agent_idle_at is not None
                    else None
                )
                state.wake_observed_inbound_id = inbound_row_id
            else:
                state.wake_occurrence_id = None
                state.wake_accepted_occurrence_id = None
                state.wake_observed_last_input_at = None
                state.wake_observed_last_agent_stop_at = None
                state.wake_observed_last_agent_idle_at = None
                state.wake_observed_inbound_id = None
            db_session.add(state)
            await db_session.commit()

    async def clear_procedure_event_wake_opportunity(self, *, session_id: str, occurrence_id: str) -> None:
        """Retire one wake opportunity without altering its pending event rows."""
        async with self._session() as db_session:
            await db_session.exec(
                update(db_models.ProcedureEventDeliverySession)
                .where(db_models.ProcedureEventDeliverySession.session_id == session_id)
                .where(db_models.ProcedureEventDeliverySession.wake_occurrence_id == occurrence_id)
                .values(
                    wake_occurrence_id=None,
                    wake_accepted_occurrence_id=None,
                    wake_observed_last_input_at=None,
                    wake_observed_last_agent_stop_at=None,
                    wake_observed_last_agent_idle_at=None,
                    wake_observed_inbound_id=None,
                )
            )
            await db_session.commit()

    async def admit_procedure_event_wake(
        self,
        *,
        session_id: str,
        occurrence_id: str,
        session: Session,
    ) -> bool:
        """Check a correlated wake under session runtime ownership before injection."""
        async with self._session() as db_session:
            state = (
                await db_session.exec(
                    select(db_models.ProcedureEventDeliverySession).where(
                        db_models.ProcedureEventDeliverySession.session_id == session_id
                    )
                )
            ).first()
            if (
                state is None
                or state.wake_occurrence_id != occurrence_id
                or state.wake_accepted_occurrence_id != occurrence_id
            ):
                return False
            pending_count = (
                await db_session.exec(
                    select(func.count())
                    .select_from(db_models.ProcedureEventInbox)
                    .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
                    .where(
                        db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value
                    )
                )
            ).one()
            snapshot_input = parse_iso_datetime(state.wake_observed_last_input_at)
            snapshot_stop = parse_iso_datetime(state.wake_observed_last_agent_stop_at)
            snapshot_idle = parse_iso_datetime(state.wake_observed_last_agent_idle_at)
            still_idle = (
                not is_agent_turn_running(
                    last_input_at=snapshot_input,
                    last_agent_stop_at=snapshot_stop,
                    last_agent_idle_at=snapshot_idle,
                )
                and session.last_agent_stop_at == snapshot_stop
                and session.last_agent_idle_at == snapshot_idle
                and session.agent_status is not AgentStatusValue.ACTIVE
            )
            if int(pending_count) > 0 and still_idle:
                return True
            state.wake_occurrence_id = None
            state.wake_accepted_occurrence_id = None
            state.wake_observed_last_input_at = None
            state.wake_observed_last_agent_stop_at = None
            state.wake_observed_last_agent_idle_at = None
            state.wake_observed_inbound_id = None
            db_session.add(state)
            await db_session.commit()
            return False

    async def procedure_event_wake_matches(self, *, session_id: str, occurrence_id: str) -> bool:
        """Return whether one accepted wake is the session's current event opportunity."""
        async with self._session() as db_session:
            state = (
                await db_session.exec(
                    select(db_models.ProcedureEventDeliverySession).where(
                        db_models.ProcedureEventDeliverySession.session_id == session_id
                    )
                )
            ).first()
        return (
            state is not None
            and state.wake_occurrence_id == occurrence_id
            and state.wake_accepted_occurrence_id == occurrence_id
        )

    async def accept_procedure_event(
        self,
        *,
        activation_id: str,
        responsibility_key: str,
        procedure_id: str,
        home: str,
        subject: str | None,
        event_json: str,
        identity: SubscriptionIdentity,
        attendance: SubscriptionAttendance,
        event_delivery: EventDeliveryMode,
        interruptible: bool,
    ) -> ProcedureEventRecord:
        """Persist one activation once, retaining its declared settings and order."""
        if not activation_id:
            raise ValueError(_PROCEDURE_ACTIVATION_IDENTITY_REQUIRED)
        row = db_models.ProcedureEventInbox(
            activation_id=activation_id,
            responsibility_key=responsibility_key,
            procedure_id=procedure_id,
            home=home,
            subject=subject,
            event_json=event_json,
            identity=identity.value,
            attendance=attendance.value,
            event_delivery=event_delivery.value,
            interruptible=interruptible,
            accepted_at=datetime.now(UTC).isoformat(),
        )
        async with self._session() as db_session:
            db_session.add(row)
            try:
                await db_session.commit()
                await db_session.refresh(row)
            except IntegrityError:
                await db_session.rollback()
                row = (
                    await db_session.exec(
                        select(db_models.ProcedureEventInbox).where(
                            db_models.ProcedureEventInbox.activation_id == activation_id
                        )
                    )
                ).one()
                if (
                    row.responsibility_key != responsibility_key
                    or row.procedure_id != procedure_id
                    or row.home != home
                    or row.subject != subject
                    or row.event_json != event_json
                    or row.identity != identity.value
                    or row.attendance != attendance.value
                    or row.event_delivery != event_delivery.value
                    or row.interruptible != interruptible
                ):
                    raise RuntimeError(_PROCEDURE_ACTIVATION_REPLAY_CONFLICT) from None
        return _procedure_event_record(row)

    async def list_procedure_events(
        self, *, responsibility_key: str, include_suspended: bool = False
    ) -> list[ProcedureEventRecord]:
        """Read retained events in enqueue order for one procedure responsibility."""
        outcomes = [db_models.ProcedureEventDeliveryOutcome.PENDING]
        if include_suspended:
            outcomes.append(db_models.ProcedureEventDeliveryOutcome.SUSPENDED)
        statement = (
            select(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.responsibility_key == responsibility_key)
            .where(db_models.ProcedureEventInbox.outcome.in_([outcome.value for outcome in outcomes]))
            .order_by(db_models.ProcedureEventInbox.enqueue_order.asc())
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [_procedure_event_record(row) for row in rows]

    async def get_procedure_delivery_session(self, *, session_id: str) -> ProcedureDeliverySessionRecord | None:
        """Read the delivery policy a procedure session was initialized with, or ``None`` for any other session."""
        statement = select(db_models.ProcedureEventDeliverySession).where(
            db_models.ProcedureEventDeliverySession.session_id == session_id
        )
        async with self._session() as db_session:
            row = (await db_session.exec(statement)).first()
        if row is None:
            return None
        return ProcedureDeliverySessionRecord(
            procedure_id=row.procedure_id,
            responsibility_key=row.responsibility_key,
            event_delivery=EventDeliveryMode(row.event_delivery),
            interruptible=row.interruptible,
        )

    async def list_procedure_activations(
        self,
        *,
        procedure_ids: Sequence[str],
        outcomes: Sequence[db_models.ProcedureEventDeliveryOutcome],
    ) -> list[ProcedureEventRecord]:
        """Read the retained activations of the named procedures in the given outcomes, in enqueue order.

        The reads above return only pending and suspended work, because a delivered activation was handed off;
        a census of work that was handed off but may be unfinished needs this one.
        """
        if not procedure_ids or not outcomes:
            return []
        statement = (
            select(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.procedure_id.in_(tuple(procedure_ids)))
            .where(db_models.ProcedureEventInbox.outcome.in_([outcome.value for outcome in outcomes]))
            .order_by(db_models.ProcedureEventInbox.enqueue_order.asc())
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [_procedure_event_record(row) for row in rows]

    async def assign_procedure_events(self, *, activation_ids: list[str], session_id: str) -> int:
        """Assign retained work to the current session without changing activation identity or order."""
        if not activation_ids:
            return 0
        statement = (
            update(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.activation_id.in_(activation_ids))
            .where(
                db_models.ProcedureEventInbox.outcome.in_(
                    [
                        db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                        db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                    ]
                )
            )
            .values(
                assigned_session_id=session_id,
                outcome=db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                outcome_reason=None,
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        return result.rowcount or 0

    async def get_assigned_procedure_events(self, *, session_id: str) -> list[ProcedureEventRecord]:
        """Read pending events assigned to one session in their durable enqueue order."""
        statement = (
            select(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
            .where(db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value)
            .order_by(db_models.ProcedureEventInbox.enqueue_order.asc())
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [_procedure_event_record(row) for row in rows]

    async def terminalize_procedure_events(
        self,
        *,
        activation_ids: list[str],
        outcome: db_models.ProcedureEventDeliveryOutcome,
        reason: str | None = None,
    ) -> int:
        """Set a terminal delivery handoff result for exactly the selected activations."""
        if not activation_ids or outcome not in {
            db_models.ProcedureEventDeliveryOutcome.DELIVERED,
            db_models.ProcedureEventDeliveryOutcome.FAILED,
        }:
            return 0
        statement = (
            update(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.activation_id.in_(activation_ids))
            .where(db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value)
            .values(outcome=outcome.value, outcome_reason=reason, terminal_at=datetime.now(UTC).isoformat())
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        return result.rowcount or 0

    async def initialize_procedure_delivery_session(
        self,
        *,
        session_id: str,
        procedure_id: str,
        responsibility_key: str,
        event_delivery: EventDeliveryMode,
        interruptible: bool,
        initial_entry_id: str | None = None,
    ) -> None:
        """Persist the policy for a newly initialized procedure session."""
        row = db_models.ProcedureEventDeliverySession(
            session_id=session_id,
            procedure_id=procedure_id,
            responsibility_key=responsibility_key,
            event_delivery=event_delivery.value,
            interruptible=interruptible,
            initialized_at=datetime.now(UTC).isoformat(),
            initial_entry_id=initial_entry_id,
        )
        async with self._session() as db_session:
            await db_session.merge(row)
            await db_session.commit()

    async def record_control_payload(
        self,
        *,
        session_id: str,
        body: str,
        source_key: str,
        envelope_name: str | None = None,
        envelope_fields: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        """Persist one exact producer body and return its row id and digest."""
        digest = hashlib.sha256(body.encode()).hexdigest()
        envelope_fields_json = json.dumps(envelope_fields, sort_keys=True) if envelope_fields is not None else None
        row = db_models.ControlDelivery(
            session_id=session_id,
            envelope_name=envelope_name,
            envelope_fields_json=envelope_fields_json,
            body=body,
            body_digest=digest,
            source_key=source_key,
            created_at=datetime.now(UTC).isoformat(),
        )
        async with self._session() as db_session:
            db_session.add(row)
            try:
                await db_session.commit()
                await db_session.refresh(row)
            except IntegrityError:
                await db_session.rollback()
                existing = await db_session.exec(
                    select(db_models.ControlDelivery).where(db_models.ControlDelivery.source_key == source_key)
                )
                row = existing.one()
        if row.id is None:
            raise RuntimeError("control_outbox insert did not return an id")
        return row.id, digest

    async def get_pending_control_payloads(self, *, session_id: str) -> list[ControlDeliveryRecord]:
        """Select this session's pending payloads in produced order."""
        statement = (
            select(db_models.ControlDelivery)
            .where(db_models.ControlDelivery.session_id == session_id)
            .where(db_models.ControlDelivery.outcome.is_(None))
            .order_by(db_models.ControlDelivery.id.asc())
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [_record(row) for row in rows]

    async def terminalize_control_payloads(
        self,
        *,
        session_id: str,
        row_ids: list[int],
        outcome: db_models.ControlDeliveryOutcome,
    ) -> int:
        """Terminalize exactly the selected pending payloads for one session."""
        if not row_ids:
            return 0
        now = datetime.now(UTC).isoformat()
        statement = (
            update(db_models.ControlDelivery)
            .where(db_models.ControlDelivery.session_id == session_id)
            .where(db_models.ControlDelivery.id.in_(row_ids))
            .where(db_models.ControlDelivery.outcome.is_(None))
            .values(outcome=outcome.value, terminal_at=now)
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        return result.rowcount or 0

    async def count_pending_control_payloads(self, *, session_id: str) -> int:
        """Return the indexed empty-path count for one owning session."""
        statement = (
            select(func.count())
            .select_from(db_models.ControlDelivery)
            .where(db_models.ControlDelivery.session_id == session_id)
            .where(db_models.ControlDelivery.outcome.is_(None))
        )
        async with self._session() as db_session:
            value = (await db_session.exec(statement)).one()
        return int(value)

    async def fetch_sessions_with_pending_control_payloads(self) -> list[str]:
        """Return the sessions holding at least one undelivered control payload."""
        statement = (
            select(db_models.ControlDelivery.session_id).where(db_models.ControlDelivery.outcome.is_(None)).distinct()
        )
        async with self._session() as db_session:
            return list((await db_session.exec(statement)).all())

    async def discard_pending_control_payloads(self, *, session_id: str) -> int:
        """Delete only undelivered payloads for a closing session."""
        statement = (
            delete(db_models.ControlDelivery)
            .where(db_models.ControlDelivery.session_id == session_id)
            .where(db_models.ControlDelivery.outcome.is_(None))
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        return result.rowcount or 0

    async def discard_superseded_control_payloads(
        self,
        *,
        session_id: str,
        envelope_name: str,
        key_fields: dict[str, str],
        before_row_id: int,
    ) -> list[int]:
        """Delete this session's older pending payloads a newer one declares superseded.

        A candidate is pending, shares ``envelope_name``, precedes
        ``before_row_id``, and carries every ``key_fields`` pair in its own
        stored ``envelope_fields_json`` — decoded here so callers never
        interpret outbox storage directly. The read only narrows candidates;
        the deleting statement re-asserts ``outcome IS NULL`` itself, matching
        ``discard_pending_control_payloads`` and ``terminalize_control_payloads``,
        so a candidate a concurrent drain delivers between the read and the
        delete is excluded rather than removed. Returns the ids actually
        removed, in ascending order.
        """
        statement = (
            select(db_models.ControlDelivery)
            .where(db_models.ControlDelivery.session_id == session_id)
            .where(db_models.ControlDelivery.outcome.is_(None))
            .where(db_models.ControlDelivery.envelope_name == envelope_name)
            .where(db_models.ControlDelivery.id < before_row_id)
            .order_by(db_models.ControlDelivery.id.asc())
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
            candidate_ids = [
                row.id
                for row in rows
                if row.id is not None and _envelope_fields_match(row.envelope_fields_json, key_fields)
            ]
            if not candidate_ids:
                return []
            delete_statement = (
                delete(db_models.ControlDelivery)
                .where(db_models.ControlDelivery.id.in_(candidate_ids))
                .where(db_models.ControlDelivery.outcome.is_(None))
                .returning(db_models.ControlDelivery.id)
            )
            result = await db_session.exec(delete_statement)
            removed_ids = sorted(result.scalars().all())
            await db_session.commit()
        return removed_ids
