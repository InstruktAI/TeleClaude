"""Mixin: durable session startup handover records."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel import select

from .. import db_models
from ..session_startup import (
    UNFINISHED_STARTUP_STATES,
    StartupHandover,
    StartupHandoverState,
    decode_startup_intent,
)
from ..session_status import SessionLifecycleStatus


def _handover_from_row(row: db_models.SessionStartupHandover) -> StartupHandover:
    """Rebuild the core handover record from its stored row."""
    return StartupHandover(
        session_id=row.session_id,
        intent=decode_startup_intent(row.launch_intent_json),
        state=StartupHandoverState(row.state),
    )


class DbStartupHandoversMixin:
    """Persistence operations for a session's startup intent and progress.

    The record is written with the session row (see `DbSessionsMixin.create_session`)
    and removed with it by the table's cascade.
    """

    async def get_startup_handover(self, session_id: str) -> StartupHandover | None:
        """Return the session's startup handover, or None when it recorded none."""
        stmt = select(db_models.SessionStartupHandover).where(db_models.SessionStartupHandover.session_id == session_id)
        async with self._session() as db_session:
            row = (await db_session.exec(stmt)).first()
        return _handover_from_row(row) if row is not None else None

    async def advance_startup_handover(
        self,
        session_id: str,
        *,
        expected: Collection[StartupHandoverState],
        target: StartupHandoverState,
    ) -> bool:
        """Move a startup handover to `target` only if it still holds an `expected` state.

        The condition keeps a late writer from overwriting a terminal outcome and
        makes each transition's precondition explicit.

        Returns:
            True when the handover moved, False when it held another state or none.
        """
        stmt = (
            update(db_models.SessionStartupHandover)
            .where(db_models.SessionStartupHandover.session_id == session_id)
            .where(db_models.SessionStartupHandover.state.in_([state.value for state in expected]))
            .values(state=target.value, updated_at=datetime.now(UTC).isoformat())
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
        return (result.rowcount or 0) == 1

    async def list_unfinished_startup_handovers(self) -> list[StartupHandover]:
        """Return unfinished startups of sessions that are neither closing nor closed."""
        stmt = (
            select(db_models.SessionStartupHandover)
            .join(
                db_models.Session,
                db_models.SessionStartupHandover.session_id == db_models.Session.session_id,
            )
            .where(db_models.SessionStartupHandover.state.in_([state.value for state in UNFINISHED_STARTUP_STATES]))
            .where(
                db_models.Session.lifecycle_status.in_(
                    [SessionLifecycleStatus.INITIALIZING.value, SessionLifecycleStatus.ACTIVE.value]
                )
            )
            .where(db_models.Session.closed_at.is_(None))
            .order_by(db_models.SessionStartupHandover.updated_at)
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(stmt)).all()
        return [_handover_from_row(row) for row in rows]
