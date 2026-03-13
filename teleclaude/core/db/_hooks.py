"""Mixin: DbHooksMixin."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models
from ..dates import parse_iso_datetime
from ._rows import HookOutboxRow

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbHooksMixin:
    async def get_agent_availability(self, agent: str) -> dict[str, bool | str | None] | None:
        """Get agent availability status.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")

        Returns:
            Dict with 'available', 'unavailable_until', 'degraded_until', 'reason', 'status' or None if not found
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            if not row:
                return None
            unavailable_until = row.unavailable_until
            if unavailable_until is not None:
                parsed_until = self._parse_iso_datetime(unavailable_until)
                if parsed_until and parsed_until < datetime.now(UTC):
                    row.available = 1
                    row.unavailable_until = None
                    row.degraded_until = None
                    row.reason = None
                    db_session.add(row)
                    await db_session.commit()
                    return {
                        "available": True,
                        "unavailable_until": None,
                        "degraded_until": None,
                        "reason": None,
                        "status": "available",
                    }
            # Check degraded_until expiry inline
            degraded_until = row.degraded_until
            if degraded_until is not None:
                parsed_degraded = self._parse_iso_datetime(degraded_until)
                if parsed_degraded and parsed_degraded < datetime.now(UTC):
                    row.degraded_until = None
                    if row.reason and row.reason.startswith("degraded"):
                        row.reason = None
                    db_session.add(row)
                    await db_session.commit()
            reason = row.reason or None
            status = "available"
            if reason and reason.startswith("degraded"):
                status = "degraded"
            elif not bool(row.available):
                status = "unavailable"
            return {
                "available": bool(row.available) if row.available is not None else False,
                "unavailable_until": unavailable_until,
                "degraded_until": row.degraded_until,
                "reason": reason,
                "status": status,
            }

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        """Parse ISO datetime with support for trailing 'Z'."""
        parsed = parse_iso_datetime(value)
        if parsed is None:
            logger.warning("Failed to parse unavailable_until value: %s", value)
        return parsed

    async def mark_agent_unavailable(self, agent: str, unavailable_until: str, reason: str) -> None:
        """Mark an agent as unavailable until a specified time.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
            unavailable_until: ISO timestamp when agent becomes available again
            reason: Reason for unavailability (e.g., "quota_exhausted", "rate_limited")
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            if row is None:
                row = db_models.AgentAvailability(
                    agent=agent,
                    available=0,
                    unavailable_until=unavailable_until,
                    degraded_until=None,
                    reason=reason,
                )
            else:
                row.available = 0
                row.unavailable_until = unavailable_until
                row.degraded_until = None
                row.reason = reason
            db_session.add(row)
            await db_session.commit()
        logger.info("Marked agent %s unavailable until %s (%s)", agent, unavailable_until, reason)

    async def mark_agent_available(self, agent: str) -> None:
        """Mark an agent as available immediately.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            if row is None:
                row = db_models.AgentAvailability(agent=agent, available=1)
            else:
                row.available = 1
                row.unavailable_until = None
                row.degraded_until = None
                row.reason = None
            db_session.add(row)
            await db_session.commit()
        logger.info("Marked agent %s available", agent)

    async def mark_agent_degraded(self, agent: str, reason: str, degraded_until: str | None = None) -> None:
        """Mark an agent as degraded (manual-only, excluded from auto-selection)."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            degraded_reason = reason if reason.startswith("degraded") else f"degraded:{reason}"
            if row is None:
                row = db_models.AgentAvailability(
                    agent=agent,
                    available=1,
                    unavailable_until=None,
                    degraded_until=degraded_until,
                    reason=degraded_reason,
                )
            else:
                row.available = 1
                row.unavailable_until = None
                row.degraded_until = degraded_until
                row.reason = degraded_reason
            db_session.add(row)
            await db_session.commit()
        logger.info("Marked agent %s degraded (%s)", agent, degraded_reason)

    async def clear_expired_agent_availability(self) -> int:
        """Reset agents whose unavailable_until or degraded_until time has passed.

        Returns:
            Number of agents reset to available
        """
        from sqlalchemy import and_, or_, update

        now = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.AgentAvailability)
            .where(
                or_(
                    and_(
                        db_models.AgentAvailability.unavailable_until.is_not(None),
                        db_models.AgentAvailability.unavailable_until < now,
                    ),
                    and_(
                        db_models.AgentAvailability.degraded_until.is_not(None),
                        db_models.AgentAvailability.degraded_until < now,
                    ),
                )
            )
            .values(available=1, unavailable_until=None, degraded_until=None, reason=None)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            cleared = result.rowcount or 0
        if cleared > 0:
            logger.info("Cleared availability for %d agents (TTL expired)", cleared)
        return cleared

    async def enqueue_hook_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> int:
        """Persist a hook event in the outbox for durable delivery."""
        now = datetime.now(UTC).isoformat()
        payload_json = json.dumps(payload)
        async with self._session() as db_session:
            row = db_models.HookOutbox(
                session_id=session_id,
                event_type=event_type,
                payload=payload_json,
                created_at=now,
                next_attempt_at=now,
                attempt_count=0,
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            if row.id is None:
                raise RuntimeError("Failed to insert hook outbox row")
            return int(row.id)

    async def fetch_hook_outbox_batch(
        self,
        now_iso: str,
        limit: int,
        lock_cutoff_iso: str,
    ) -> list[HookOutboxRow]:
        """Fetch a batch of due hook events."""
        from sqlmodel import select

        stmt = (
            select(db_models.HookOutbox)
            .where(db_models.HookOutbox.delivered_at.is_(None))
            .where(db_models.HookOutbox.next_attempt_at <= now_iso)
            .where((db_models.HookOutbox.locked_at.is_(None)) | (db_models.HookOutbox.locked_at <= lock_cutoff_iso))
            .order_by(db_models.HookOutbox.created_at)
            .limit(limit)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [
                HookOutboxRow(
                    id=row.id or 0,
                    session_id=row.session_id,
                    event_type=row.event_type,
                    payload=row.payload,
                    created_at=row.created_at,
                    attempt_count=row.attempt_count,
                )
                for row in rows
            ]

    async def claim_hook_outbox(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """Claim a hook outbox row for processing."""
        from sqlalchemy import or_, update

        stmt = (
            update(db_models.HookOutbox)
            .where(
                db_models.HookOutbox.id == row_id,
                db_models.HookOutbox.delivered_at.is_(None),
                or_(
                    db_models.HookOutbox.locked_at.is_(None),
                    db_models.HookOutbox.locked_at <= lock_cutoff_iso,
                ),
            )
            .values(locked_at=now_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def claim_hook_outbox_batch(self, row_ids: list[int], now_iso: str, lock_cutoff_iso: str) -> set[int]:
        """Claim multiple hook outbox rows in a single DB round-trip.

        Returns the set of row IDs that were successfully claimed.
        """
        if not row_ids:
            return set()
        from sqlalchemy import or_, update

        stmt = (
            update(db_models.HookOutbox)
            .where(
                db_models.HookOutbox.id.in_(row_ids),
                db_models.HookOutbox.delivered_at.is_(None),
                or_(
                    db_models.HookOutbox.locked_at.is_(None),
                    db_models.HookOutbox.locked_at <= lock_cutoff_iso,
                ),
            )
            .values(locked_at=now_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            claimed_count = result.rowcount or 0

        # If all were claimed, return all IDs. Otherwise, we need to check which ones.
        if claimed_count == len(row_ids):
            return set(row_ids)

        # Fall back to checking which rows are now locked by us
        from sqlmodel import select

        stmt_check = select(db_models.HookOutbox.id).where(
            db_models.HookOutbox.id.in_(row_ids),
            db_models.HookOutbox.locked_at == now_iso,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt_check)
            return {int(row_id) for row_id in result.all()}

    async def mark_hook_outbox_delivered(self, row_id: int, error: str | None = None) -> None:
        """Mark a hook outbox row delivered (optionally capturing last error)."""
        from sqlalchemy import update

        now = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.HookOutbox)
            .where(db_models.HookOutbox.id == row_id)
            .values(delivered_at=now, last_error=error, locked_at=None)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_hook_outbox_failed(
        self,
        row_id: int,
        attempt_count: int,
        next_attempt_at: str,
        error: str,
    ) -> None:
        """Record a hook outbox failure and schedule a retry."""
        from sqlalchemy import update

        stmt = (
            update(db_models.HookOutbox)
            .where(db_models.HookOutbox.id == row_id)
            .values(
                attempt_count=attempt_count,
                next_attempt_at=next_attempt_at,
                last_error=error,
                locked_at=None,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    # ── Inbound queue — durable message delivery ─────────────────────────
