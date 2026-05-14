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


async def test_cleanup_webhook_outbox_deletes_only_expired_terminal_rows(db: Db) -> None:
    old_delivered_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"old-delivered"}',
        target_url="https://example.test/old",
    )
    recent_delivered_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"recent-delivered"}',
        target_url="https://example.test/recent",
    )
    pending_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"pending"}',
        target_url="https://example.test/pending",
    )
    rejected_id = await db.enqueue_webhook(
        "contract-1",
        event_json='{"event":"rejected"}',
        target_url="https://example.test/rejected",
    )
    old_iso = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    recent_iso = datetime.now(UTC).isoformat()
    await db.mark_webhook_delivered(old_delivered_id)
    await db.mark_webhook_delivered(recent_delivered_id)
    await db.mark_webhook_failed(rejected_id, error="gone", attempt_count=1, next_attempt_at=None, status="rejected")

    async with db._session() as session:
        for row_id in [old_delivered_id, rejected_id]:
            row = await session.get(db_models.WebhookOutbox, row_id)
            assert row is not None
            row.created_at = old_iso
            session.add(row)
        recent = await session.get(db_models.WebhookOutbox, recent_delivered_id)
        assert recent is not None
        recent.created_at = recent_iso
        session.add(recent)
        pending = await session.get(db_models.WebhookOutbox, pending_id)
        assert pending is not None
        pending.created_at = old_iso
        session.add(pending)
        await session.commit()

    deleted = await db.cleanup_webhook_outbox(older_than_iso=(datetime.now(UTC) - timedelta(days=7)).isoformat())

    async with db._session() as session:
        old_delivered = await session.get(db_models.WebhookOutbox, old_delivered_id)
        rejected = await session.get(db_models.WebhookOutbox, rejected_id)
        recent_delivered = await session.get(db_models.WebhookOutbox, recent_delivered_id)
        pending_row = await session.get(db_models.WebhookOutbox, pending_id)

    assert deleted == 2
    assert old_delivered is None
    assert rejected is None
    assert recent_delivered is not None
    assert pending_row is not None
