"""Mixin: DbWebhooksMixin."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbWebhooksMixin:
    async def upsert_webhook_contract(self, contract_id: str, contract_json: str, source: str = "api") -> None:
        """Insert or update a webhook contract."""
        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            existing = await db_session.get(db_models.WebhookContract, contract_id)
            if existing:
                existing.contract_json = contract_json
                existing.source = source
                existing.updated_at = now
                existing.active = 1
                db_session.add(existing)
            else:
                row = db_models.WebhookContract(
                    id=contract_id,
                    contract_json=contract_json,
                    active=1,
                    source=source,
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(row)
            await db_session.commit()

    async def deactivate_webhook_contract(self, contract_id: str) -> bool:
        """Deactivate a webhook contract. Returns True if found."""
        from sqlalchemy import update

        now = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.WebhookContract)
            .where(db_models.WebhookContract.id == contract_id)
            .values(active=0, updated_at=now)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) > 0

    async def list_webhook_contracts(self, active_only: bool = True) -> list[db_models.WebhookContract]:
        """List webhook contracts."""
        from sqlmodel import select

        stmt = select(db_models.WebhookContract)
        if active_only:
            stmt = stmt.where(db_models.WebhookContract.active == 1)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    # ── Webhook outbox CRUD ─────────────────────────────────────────────

    async def enqueue_webhook(
        self, contract_id: str, event_json: str, target_url: str, target_secret: str | None = None
    ) -> int:
        """Add an event to the webhook outbox for external delivery."""
        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            row = db_models.WebhookOutbox(
                contract_id=contract_id,
                event_json=event_json,
                target_url=target_url,
                target_secret=target_secret,
                status="pending",
                created_at=now,
                next_attempt_at=now,
                attempt_count=0,
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            if row.id is None:
                raise RuntimeError("Failed to insert webhook outbox row")
            return int(row.id)

    async def fetch_webhook_batch(self, limit: int, now_iso: str) -> list[db_models.WebhookOutbox]:
        """Fetch a batch of due webhook deliveries."""
        from sqlmodel import select

        stmt = (
            select(db_models.WebhookOutbox)
            .where(db_models.WebhookOutbox.status == "pending")
            .where(db_models.WebhookOutbox.next_attempt_at <= now_iso)
            .where(db_models.WebhookOutbox.locked_at.is_(None))
            .order_by(db_models.WebhookOutbox.created_at)
            .limit(limit)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def claim_webhook(self, row_id: int, now_iso: str) -> bool:
        """Claim a webhook outbox row for delivery."""
        from sqlalchemy import update

        stmt = (
            update(db_models.WebhookOutbox)
            .where(
                db_models.WebhookOutbox.id == row_id,
                db_models.WebhookOutbox.status == "pending",
                db_models.WebhookOutbox.locked_at.is_(None),
            )
            .values(locked_at=now_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def mark_webhook_delivered(self, row_id: int) -> None:
        """Mark a webhook delivery as successful."""
        from sqlalchemy import update

        now = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.WebhookOutbox)
            .where(db_models.WebhookOutbox.id == row_id)
            .values(status="delivered", delivered_at=now, locked_at=None)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_webhook_failed(
        self,
        row_id: int,
        error: str,
        attempt_count: int,
        next_attempt_at: str | None,
        status: str = "pending",
    ) -> None:
        """Record a webhook delivery failure and schedule retry."""
        from sqlalchemy import update

        stmt = (
            update(db_models.WebhookOutbox)
            .where(db_models.WebhookOutbox.id == row_id)
            .values(
                attempt_count=attempt_count,
                next_attempt_at=next_attempt_at,
                last_error=error,
                status=status,
                locked_at=None,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    # ── Session listeners (durable PUB-SUB) ──────────────────────────
