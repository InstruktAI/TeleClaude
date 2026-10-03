"""Mixin: durable event-subscription records."""

from __future__ import annotations

from sqlalchemy import delete, update
from sqlmodel import select

from .. import db_models


class DbEventSubscriptionsMixin:
    """Persistence operations for session-owned event subscriptions."""

    async def insert_event_subscription(self, row: db_models.EventSubscriptionRow) -> None:
        """Persist one newly-created subscription."""
        async with self._session() as db_session:
            db_session.add(row)
            await db_session.commit()

    async def list_event_subscriptions_for_session(self, session_id: str) -> list[db_models.EventSubscriptionRow]:
        """List subscriptions owned by one session."""
        statement = (
            select(db_models.EventSubscriptionRow)
            .where(db_models.EventSubscriptionRow.session_id == session_id)
            .order_by(db_models.EventSubscriptionRow.created_at, db_models.EventSubscriptionRow.id)
        )
        async with self._session() as db_session:
            return list((await db_session.exec(statement)).all())

    async def list_all_event_subscriptions(self) -> list[db_models.EventSubscriptionRow]:
        """List subscriptions for rebuilding the in-memory delivery index."""
        statement = select(db_models.EventSubscriptionRow).order_by(
            db_models.EventSubscriptionRow.created_at, db_models.EventSubscriptionRow.id
        )
        async with self._session() as db_session:
            return list((await db_session.exec(statement)).all())

    async def delete_event_subscription(self, subscription_id: str, session_id: str) -> bool:
        """Withdraw one subscription only when it belongs to the supplied session."""
        statement = delete(db_models.EventSubscriptionRow).where(
            db_models.EventSubscriptionRow.id == subscription_id,
            db_models.EventSubscriptionRow.session_id == session_id,
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
            return bool(result.rowcount)

    async def delete_event_subscriptions_for_session(self, session_id: str) -> list[str]:
        """Remove every subscription owned by a closing session and return its ids."""
        statement = (
            delete(db_models.EventSubscriptionRow)
            .where(db_models.EventSubscriptionRow.session_id == session_id)
            .returning(db_models.EventSubscriptionRow.id)
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            subscription_ids = sorted(result.scalars().all())
            await db_session.commit()
            return subscription_ids

    async def claim_event_subscription(self, subscription_id: str, event_id: str) -> bool:
        """Claim a once subscription for one event, idempotently."""
        statement = (
            update(db_models.EventSubscriptionRow)
            .where(db_models.EventSubscriptionRow.id == subscription_id)
            .where(
                (db_models.EventSubscriptionRow.claimed_event_id.is_(None))
                | (db_models.EventSubscriptionRow.claimed_event_id == event_id)
            )
            .values(claimed_event_id=event_id)
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
            return bool(result.rowcount)

    async def delete_event_subscription_by_id(self, subscription_id: str) -> bool:
        """Remove a spent subscription by its durable identity."""
        statement = delete(db_models.EventSubscriptionRow).where(db_models.EventSubscriptionRow.id == subscription_id)
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
            return bool(result.rowcount)

    async def delete_event_subscriptions_for_closed_sessions(self) -> list[str]:
        """Remove closed-session records and return their ids."""
        live_session = (
            select(db_models.Session.session_id)
            .where(db_models.Session.session_id == db_models.EventSubscriptionRow.session_id)
            .where(db_models.Session.closed_at.is_(None))
            .exists()
        )
        statement = (
            delete(db_models.EventSubscriptionRow).where(~live_session).returning(db_models.EventSubscriptionRow.id)
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            subscription_ids = sorted(result.scalars().all())
            await db_session.commit()
            return subscription_ids
