"""Mixin: the inbox outcomes of single-claim responsibilities, and assignment that settles against the target's close."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, update
from sqlmodel import select

from .. import db_models
from ..session_status import SessionLifecycleStatus
from ._control_delivery import ProcedureEventRecord, _procedure_event_record

_CLOSE_STARTED_STATUSES = (SessionLifecycleStatus.CLOSING.value, SessionLifecycleStatus.CLOSED.value)


class DbSingleClaimDeliveryMixin:
    """Persistence seam for ``not delivered`` outcomes and conditional assignment of single-claim activations."""

    async def not_deliver_procedure_event(self, *, activation_id: str, reason: str) -> int:
        """End one pending or suspended activation as ``not delivered``; its assignee, if any, is retained."""
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
                    outcome=db_models.ProcedureEventDeliveryOutcome.NOT_DELIVERED.value,
                    outcome_reason=reason,
                    terminal_at=datetime.now(UTC).isoformat(),
                )
            )
            await db_session.commit()
        return result.rowcount or 0

    async def not_deliver_session_procedure_events(
        self, *, session_id: str, procedure_ids: Sequence[str], reason: str
    ) -> int:
        """End a closed session's pending work of the named procedures as ``not delivered``, keeping its assignee."""
        async with self._session() as db_session:
            result = await db_session.exec(
                update(db_models.ProcedureEventInbox)
                .where(db_models.ProcedureEventInbox.assigned_session_id == session_id)
                .where(db_models.ProcedureEventInbox.outcome == db_models.ProcedureEventDeliveryOutcome.PENDING.value)
                .where(db_models.ProcedureEventInbox.procedure_id.in_(list(procedure_ids)))
                .values(
                    outcome=db_models.ProcedureEventDeliveryOutcome.NOT_DELIVERED.value,
                    outcome_reason=reason,
                    terminal_at=datetime.now(UTC).isoformat(),
                )
            )
            await db_session.commit()
        return result.rowcount or 0

    async def list_unassigned_responsibility_events(self, *, responsibility_key: str) -> list[ProcedureEventRecord]:
        """The pending or suspended activations of a responsibility that no session has been assigned."""
        async with self._session() as db_session:
            rows = (
                await db_session.exec(
                    select(db_models.ProcedureEventInbox)
                    .where(db_models.ProcedureEventInbox.responsibility_key == responsibility_key)
                    .where(db_models.ProcedureEventInbox.assigned_session_id.is_(None))  # type: ignore[union-attr]
                    .where(
                        db_models.ProcedureEventInbox.outcome.in_(
                            [
                                db_models.ProcedureEventDeliveryOutcome.PENDING.value,
                                db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value,
                            ]
                        )
                    )
                    .order_by(db_models.ProcedureEventInbox.enqueue_order)  # type: ignore[arg-type]
                )
            ).all()
        return [_procedure_event_record(row) for row in rows]

    async def assign_procedure_events_unless_closed(
        self, *, activation_ids: list[str], session_id: str, reason: str
    ) -> list[db_models.ProcedureEventDeliveryOutcome]:
        """Assign retained work to a session in one statement that reads the session\'s lifecycle in the same write.

        A target that is still open takes the rows as pending. A target that has closed takes them too, but as
        ``not delivered`` with the reason, so the assignee is retained and no row stays pending on a closed session. The
        close persists the session\'s closed state before it sweeps its rows, so whichever order the two interleave in,
        every row ends either swept by the close or settled here. The outcome each row ended in is returned.
        """
        if not activation_ids:
            return []
        open_target = (
            select(func.count())
            .select_from(db_models.Session)
            .where(db_models.Session.session_id == session_id)
            .where(db_models.Session.closed_at.is_(None))  # type: ignore[union-attr]
            .where(
                or_(
                    db_models.Session.lifecycle_status.is_(None),  # type: ignore[union-attr]
                    db_models.Session.lifecycle_status.notin_(_CLOSE_STARTED_STATUSES),  # type: ignore[union-attr]
                )
            )
            .scalar_subquery()
        )
        pending = db_models.ProcedureEventDeliveryOutcome.PENDING.value
        gone = db_models.ProcedureEventDeliveryOutcome.NOT_DELIVERED.value
        statement = (
            update(db_models.ProcedureEventInbox)
            .where(db_models.ProcedureEventInbox.activation_id.in_(activation_ids))
            .where(
                db_models.ProcedureEventInbox.outcome.in_(
                    [pending, db_models.ProcedureEventDeliveryOutcome.SUSPENDED.value]
                )
            )
            .values(
                assigned_session_id=session_id,
                outcome=case((open_target > 0, pending), else_=gone),
                outcome_reason=case((open_target > 0, None), else_=reason),
                terminal_at=case((open_target > 0, None), else_=datetime.now(UTC).isoformat()),
            )
            .returning(db_models.ProcedureEventInbox.outcome)
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
            await db_session.commit()
        return [db_models.ProcedureEventDeliveryOutcome(row[0]) for row in rows]
