"""Mixin: DbHooksMixin."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy import delete, or_, true, update
from sqlmodel import select

from teleclaude.config.machine import config
from teleclaude.core.agent_availability import AgentAvailabilityStatus, AvailabilityState
from teleclaude.core.runtime_events import publish_agent_availability

from .. import db_models
from ._rows import HookOutboxRow

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)
_AGENT_WIDE_MODEL = ""


class DbHooksMixin:
    """Agent availability and hook outbox persistence helpers."""

    @staticmethod
    def _availability_state(row: db_models.AgentAvailability) -> AvailabilityState:
        """Decode the persisted status value at the store boundary."""
        return AvailabilityState(AgentAvailabilityStatus(row.status), row.status_until, row.reason)

    @staticmethod
    async def _emit_agent_availability_event(
        *,
        agent: str,
        status: AgentAvailabilityStatus | None,
        status_until: str | None = None,
        reason: str | None = None,
        error: str | None = None,
        model: str | None = None,
        model_status: AgentAvailabilityStatus | None = None,
        model_status_until: str | None = None,
        model_reason: str | None = None,
    ) -> None:
        """Broadcast a live agent availability change event."""
        await publish_agent_availability(
            config.computer.name,
            agent,
            status=status,
            status_until=status_until,
            reason=reason,
            error=error,
            model=model,
            model_status=model_status,
            model_status_until=model_status_until,
            model_reason=model_reason,
        )

    async def get_agent_availability(self, agent: str) -> AvailabilityState | None:
        """Get the normalized agent-wide availability state."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, (agent, _AGENT_WIDE_MODEL))
            if not row:
                return None
            persisted_state = self._availability_state(row)
            state = persisted_state.normalized(datetime.now(UTC))
            if state != persisted_state:
                row.status = state.status.value
                row.status_until = state.status_until
                row.reason = state.reason
                db_session.add(row)
                await db_session.commit()
            return state

    async def list_model_availability(self, agent: str) -> dict[str, AvailabilityState]:
        """List normalized, non-available model-scoped states for an agent."""
        statement = (
            select(db_models.AgentAvailability)
            .where(db_models.AgentAvailability.agent == agent)
            .where(db_models.AgentAvailability.model != _AGENT_WIDE_MODEL)
        )
        async with self._session() as db_session:
            rows = list(await db_session.exec(statement))
            states: dict[str, AvailabilityState] = {}
            for row in rows:
                persisted_state = self._availability_state(row)
                state = persisted_state.normalized(datetime.now(UTC))
                if state != persisted_state:
                    row.status = state.status.value
                    row.status_until = state.status_until
                    row.reason = state.reason
                    db_session.add(row)
                if state.status is not AgentAvailabilityStatus.AVAILABLE:
                    states[row.model] = state
            await db_session.commit()
        return states

    async def set_agent_availability(self, agent: str, model: str, state: AvailabilityState) -> None:
        """Persist one agent-wide or model-scoped availability state."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, (agent, model))
            if row is None:
                row = db_models.AgentAvailability(
                    agent=agent,
                    model=model,
                    status=state.status.value,
                    status_until=state.status_until,
                    reason=state.reason,
                )
            else:
                row.status = state.status.value
                row.status_until = state.status_until
                row.reason = state.reason
            db_session.add(row)
            await db_session.commit()

    async def mark_agent_unavailable(
        self,
        agent: str,
        unavailable_until: str,
        reason: str,
        *,
        model: str = _AGENT_WIDE_MODEL,
    ) -> None:
        """Mark an agent as unavailable until a specified time.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
            unavailable_until: ISO timestamp when agent becomes available again
            reason: Reason for unavailability (e.g., "quota_exhausted", "rate_limited")
        """
        state = AvailabilityState(AgentAvailabilityStatus.UNAVAILABLE, unavailable_until, reason)
        await self.set_agent_availability(agent, model, state)
        if model:
            agent_info = await self.get_agent_availability(agent)
            await self._emit_agent_availability_event(
                agent=agent,
                status=agent_info.status if agent_info else AgentAvailabilityStatus.AVAILABLE,
                status_until=agent_info.status_until if agent_info else None,
                reason=agent_info.reason if agent_info else None,
                model=model,
                model_status=state.status,
                model_status_until=state.status_until,
                model_reason=reason,
            )
        else:
            await self._emit_agent_availability_event(
                agent=agent,
                status=AgentAvailabilityStatus.UNAVAILABLE,
                status_until=unavailable_until,
                reason=reason,
            )
        logger.info("Marked agent %s unavailable until %s (%s)", agent, unavailable_until, reason)

    async def mark_agent_available(self, agent: str, *, model: str = _AGENT_WIDE_MODEL) -> None:
        """Mark an agent as available immediately.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
        """
        await self.set_agent_availability(
            agent, model, AvailabilityState(AgentAvailabilityStatus.AVAILABLE, None, None)
        )
        if model:
            agent_info = await self.get_agent_availability(agent)
            await self._emit_agent_availability_event(
                agent=agent,
                status=agent_info.status if agent_info else AgentAvailabilityStatus.AVAILABLE,
                status_until=agent_info.status_until if agent_info else None,
                reason=agent_info.reason if agent_info else None,
                model=model,
                model_status=AgentAvailabilityStatus.AVAILABLE,
            )
        else:
            await self._emit_agent_availability_event(agent=agent, status=AgentAvailabilityStatus.AVAILABLE)
        logger.info("Marked agent %s available", agent)

    async def mark_agent_degraded(
        self,
        agent: str,
        reason: str,
        degraded_until: str | None = None,
        *,
        model: str = _AGENT_WIDE_MODEL,
    ) -> None:
        """Mark an agent as degraded (manual-only, excluded from auto-selection)."""
        state = AvailabilityState(AgentAvailabilityStatus.DEGRADED, degraded_until, reason)
        await self.set_agent_availability(agent, model, state)
        if model:
            agent_info = await self.get_agent_availability(agent)
            await self._emit_agent_availability_event(
                agent=agent,
                status=agent_info.status if agent_info else AgentAvailabilityStatus.AVAILABLE,
                status_until=agent_info.status_until if agent_info else None,
                reason=agent_info.reason if agent_info else None,
                model=model,
                model_status=state.status,
                model_status_until=state.status_until,
                model_reason=reason,
            )
        else:
            await self._emit_agent_availability_event(
                agent=agent,
                status=AgentAvailabilityStatus.DEGRADED,
                status_until=degraded_until,
                reason=reason,
            )
        logger.info("Marked agent %s degraded (%s)", agent, reason)

    async def clear_expired_agent_availability(self) -> int:
        """Reset availability subjects whose status expiry has passed.

        Returns:
            Number of agents reset to available
        """
        now = datetime.now(UTC).isoformat()
        select_stmt = select(db_models.AgentAvailability.agent, db_models.AgentAvailability.model).where(
            db_models.AgentAvailability.status_until.is_not(None),
            db_models.AgentAvailability.status_until < now,
        )
        stmt = (
            update(db_models.AgentAvailability)
            .where(
                db_models.AgentAvailability.status_until.is_not(None),
                db_models.AgentAvailability.status_until < now,
            )
            .values(status=AgentAvailabilityStatus.AVAILABLE.value, status_until=None, reason=None)
        )
        async with self._session() as db_session:
            expired_agents = list(await db_session.exec(select_stmt))
            result = await db_session.exec(stmt)
            await db_session.commit()
            cleared = result.rowcount or 0
        if cleared > 0:
            for agent, model in expired_agents:
                if model == _AGENT_WIDE_MODEL:
                    await self._emit_agent_availability_event(agent=agent, status=AgentAvailabilityStatus.AVAILABLE)
                else:
                    agent_info = await self.get_agent_availability(agent)
                    await self._emit_agent_availability_event(
                        agent=agent,
                        status=agent_info.status if agent_info else AgentAvailabilityStatus.AVAILABLE,
                        status_until=agent_info.status_until if agent_info else None,
                        reason=agent_info.reason if agent_info else None,
                        model=model,
                        model_status=AgentAvailabilityStatus.AVAILABLE,
                    )
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
        async with self._outbox_session() as db_session:
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
        exclude_session_ids: frozenset[str] | None = None,
    ) -> list[HookOutboxRow]:
        """Fetch a batch of due hook events."""
        stmt = (
            select(db_models.HookOutbox)
            .where(db_models.HookOutbox.next_attempt_at <= now_iso)
            .where((db_models.HookOutbox.locked_at.is_(None)) | (db_models.HookOutbox.locked_at <= lock_cutoff_iso))
        )
        if exclude_session_ids:
            stmt = stmt.where(db_models.HookOutbox.session_id.notin_(exclude_session_ids))
        stmt = stmt.order_by(db_models.HookOutbox.created_at).limit(limit)
        async with self._outbox_session() as db_session:
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

    async def has_undispatched_hook_events(self, session_id: str) -> bool:
        """Return whether the session still has hook events the dispatcher has not settled."""
        stmt = select(db_models.HookOutbox.id).where(db_models.HookOutbox.session_id == session_id).limit(1)
        async with self._outbox_session() as db_session:
            result = await db_session.exec(stmt)
            return result.first() is not None

    async def claim_hook_outbox(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """Claim a hook outbox row for processing."""
        stmt = (
            update(db_models.HookOutbox)
            .where(
                db_models.HookOutbox.id == row_id,
                or_(
                    db_models.HookOutbox.locked_at.is_(None),
                    db_models.HookOutbox.locked_at <= lock_cutoff_iso,
                ),
            )
            .values(locked_at=now_iso)
        )
        async with self._outbox_session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def claim_hook_outbox_batch(self, row_ids: list[int], now_iso: str, lock_cutoff_iso: str) -> set[int]:
        """Claim multiple hook outbox rows in a single DB round-trip.

        Returns the set of row IDs that were successfully claimed.
        """
        if not row_ids:
            return set()

        stmt = (
            update(db_models.HookOutbox)
            .where(
                db_models.HookOutbox.id.in_(row_ids),
                or_(
                    db_models.HookOutbox.locked_at.is_(None),
                    db_models.HookOutbox.locked_at <= lock_cutoff_iso,
                ),
            )
            .values(locked_at=now_iso)
        )
        async with self._outbox_session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            claimed_count = result.rowcount or 0

        # If all were claimed, return all IDs. Otherwise, we need to check which ones.
        if claimed_count == len(row_ids):
            return set(row_ids)

        # Fall back to checking which rows are now locked by us
        stmt_check = select(db_models.HookOutbox.id).where(
            db_models.HookOutbox.id.in_(row_ids),
            db_models.HookOutbox.locked_at == now_iso,
        )
        async with self._outbox_session() as db_session:
            result = await db_session.exec(stmt_check)
            return {int(row_id) for row_id in result.all()}

    async def delete_hook_outbox_row(self, row_id: int) -> None:
        """Delete a processed hook outbox row."""
        stmt = delete(db_models.HookOutbox).where(db_models.HookOutbox.id == row_id)
        async with self._outbox_session() as db_session:
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
        async with self._outbox_session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def defer_hook_outbox_row(self, row_id: int, next_attempt_at: str) -> None:
        """Release a row's claim and make it due again later, leaving its attempt count untouched."""
        stmt = (
            update(db_models.HookOutbox)
            .where(db_models.HookOutbox.id == row_id)
            .values(next_attempt_at=next_attempt_at, locked_at=None)
        )
        async with self._outbox_session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def cleanup_hook_outbox(self, older_than_iso: str) -> int:
        """Delete expired hook outbox rows or rows whose session is no longer live."""
        live_session_ids = await self._retained_session_ids()

        orphan_condition = db_models.HookOutbox.session_id.notin_(live_session_ids) if live_session_ids else true()
        stmt = delete(db_models.HookOutbox).where(
            or_(
                db_models.HookOutbox.created_at < older_than_iso,
                orphan_condition,
            )
        )
        async with self._outbox_session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    # ── Inbound queue — durable message delivery ─────────────────────────
