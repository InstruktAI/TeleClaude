"""Persistence owned by the control-delivery bounded context."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from teleclaude.core import db_models


@dataclass(frozen=True)
class ControlDeliveryRecord:
    """One selected control payload, ordered by durable row identity."""

    id: int
    session_id: str
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
        body=row.body,
        body_digest=row.body_digest,
        created_at=row.created_at,
        outcome=outcome,
        terminal_at=row.terminal_at,
    )


class DbControlDeliveryMixin:
    """Public persistence seam for producer handoff, drain, and close cleanup."""

    async def record_control_payload(self, *, session_id: str, body: str, source_key: str) -> tuple[int, str]:
        """Persist one exact producer body and return its row id and digest."""
        digest = hashlib.sha256(body.encode()).hexdigest()
        row = db_models.ControlDelivery(
            session_id=session_id,
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
