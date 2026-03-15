from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.core import db_models
from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_enqueue_inbound_skips_duplicate_source_message_ids(db: Db) -> None:
    first_id = await db.enqueue_inbound(
        "sess-001",
        "discord",
        "hello",
        source_message_id="msg-1",
        source_channel_id="chan-1",
    )
    second_id = await db.enqueue_inbound(
        "sess-002",
        "discord",
        "hello again",
        source_message_id="msg-1",
        source_channel_id="chan-2",
    )

    assert isinstance(first_id, int)
    assert second_id is None


async def test_claim_and_fetch_pending_inbound_respect_retry_and_lock_cutoffs(db: Db) -> None:
    first_id = await db.enqueue_inbound("sess-001", "discord", "hello")
    second_id = await db.enqueue_inbound("sess-001", "discord", "retry")
    assert first_id is not None
    assert second_id is not None

    now_iso = datetime.now(UTC).isoformat()
    stale_lock = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    claimed = await db.claim_inbound(first_id, now_iso=now_iso, lock_cutoff_iso=stale_lock)
    await db.mark_inbound_failed(second_id, "retryable", now_iso=now_iso, backoff_seconds=30)

    due_now = await db.fetch_inbound_pending(
        "sess-001",
        limit=10,
        now_iso=now_iso,
        lock_cutoff_iso=stale_lock,
    )
    due_later = await db.fetch_inbound_pending(
        "sess-001",
        limit=10,
        now_iso=(datetime.now(UTC) + timedelta(seconds=31)).isoformat(),
        lock_cutoff_iso=stale_lock,
    )

    assert claimed is True
    assert due_now == []
    assert [row["id"] for row in due_later] == [second_id]
    assert due_later[0]["status"] == "failed"
    assert due_later[0]["attempt_count"] == 1


async def test_mark_inbound_delivered_and_expired_persist_terminal_states(db: Db) -> None:
    delivered_id = await db.enqueue_inbound("sess-001", "discord", "deliver me")
    expired_id = await db.enqueue_inbound("sess-001", "discord", "expire me")
    assert delivered_id is not None
    assert expired_id is not None

    now_iso = datetime.now(UTC).isoformat()
    await db.claim_inbound(delivered_id, now_iso=now_iso, lock_cutoff_iso=now_iso)
    await db.mark_inbound_delivered(delivered_id, now_iso=now_iso)
    await db.mark_inbound_expired(expired_id, error="too old", now_iso=now_iso)

    async with db._session() as session:
        delivered = await session.get(db_models.InboundQueue, delivered_id)
        expired = await session.get(db_models.InboundQueue, expired_id)

    assert delivered is not None
    assert delivered.status == "delivered"
    assert delivered.processed_at == now_iso
    assert delivered.locked_at is None
    assert expired is not None
    assert expired.status == "expired"
    assert expired.last_error == "too old"
    assert expired.processed_at == now_iso


async def test_expire_inbound_for_session_and_cleanup_only_remove_terminal_rows(db: Db) -> None:
    pending_id = await db.enqueue_inbound("sess-001", "discord", "pending")
    delivered_id = await db.enqueue_inbound("sess-002", "discord", "delivered")
    assert pending_id is not None
    assert delivered_id is not None

    now_iso = datetime.now(UTC).isoformat()
    await db.mark_inbound_delivered(delivered_id, now_iso=now_iso)
    expired_count = await db.expire_inbound_for_session("sess-001", now_iso=now_iso)
    sessions = await db.fetch_sessions_with_pending_inbound()
    deleted = await db.cleanup_inbound(older_than_iso=(datetime.now(UTC) + timedelta(minutes=1)).isoformat())

    assert expired_count == 1
    assert sessions == []
    assert deleted == 2
