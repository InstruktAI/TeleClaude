from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.core import db_models
from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_webhook_contracts_upsert_update_list_and_deactivate(db: Db) -> None:
    await db.upsert_webhook_contract("contract-1", '{"version":1}', source="api")
    await db.upsert_webhook_contract("contract-1", '{"version":2}', source="sync")

    active = await db.list_webhook_contracts()
    deactivated = await db.deactivate_webhook_contract("contract-1")
    all_contracts = await db.list_webhook_contracts(active_only=False)

    assert [contract.contract_json for contract in active] == ['{"version":2}']
    assert active[0].source == "sync"
    assert deactivated is True
    assert len(all_contracts) == 1
    assert all_contracts[0].active == 0


async def test_enqueue_fetch_claim_and_deliver_webhooks_follow_pending_queue_rules(db: Db) -> None:
    row_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"session.updated"}',
        target_url="https://example.test/hook",
        target_secret="secret",
    )
    now_iso = datetime.now(UTC).isoformat()

    batch = await db.fetch_webhook_batch(limit=10, now_iso=now_iso)
    claimed = await db.claim_webhook(row_id, now_iso=now_iso)
    await db.mark_webhook_delivered(row_id)
    after_delivery = await db.fetch_webhook_batch(
        limit=10, now_iso=(datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    )

    assert [row.id for row in batch] == [row_id]
    assert claimed is True
    assert after_delivery == []

    async with db._session() as session:
        delivered = await session.get(db_models.WebhookOutbox, row_id)

    assert delivered is not None
    assert delivered.status == "delivered"
    assert delivered.delivered_at is not None
    assert delivered.locked_at is None


async def test_mark_webhook_failed_schedules_retry_without_making_non_pending_rows_fetchable(db: Db) -> None:
    pending_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"retry"}',
        target_url="https://example.test/retry",
    )
    terminal_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"stop"}',
        target_url="https://example.test/stop",
    )
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    await db.mark_webhook_failed(
        pending_id,
        error="timeout",
        attempt_count=2,
        next_attempt_at=future,
    )
    await db.mark_webhook_failed(
        terminal_id,
        error="permanent",
        attempt_count=9,
        next_attempt_at=None,
        status="failed",
    )

    due_now = await db.fetch_webhook_batch(limit=10, now_iso=datetime.now(UTC).isoformat())
    due_later = await db.fetch_webhook_batch(limit=10, now_iso=(datetime.now(UTC) + timedelta(minutes=11)).isoformat())

    assert due_now == []
    assert [row.id for row in due_later] == [pending_id]

    async with db._session() as session:
        pending = await session.get(db_models.WebhookOutbox, pending_id)
        terminal = await session.get(db_models.WebhookOutbox, terminal_id)

    assert pending is not None
    assert pending.attempt_count == 2
    assert pending.last_error == "timeout"
    assert terminal is not None
    assert terminal.status == "failed"
    assert terminal.last_error == "permanent"
