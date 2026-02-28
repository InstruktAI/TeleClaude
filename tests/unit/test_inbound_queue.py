"""Tests for inbound queue DB methods and InboundQueueManager."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from teleclaude.core.db import Db, InboundQueueRow
from teleclaude.core.inbound_queue import (
    InboundQueueManager,
    _backoff_for_attempt,
    init_inbound_queue_manager,
    reset_inbound_queue_manager,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past(seconds: int = 600) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _future(seconds: int = 600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@pytest.fixture
async def test_db(tmp_path: Path) -> Any:
    db = Db(str(tmp_path / "inbound-test.db"))
    await db.initialize()
    try:
        yield db
    finally:
        await db.close()


# ── DB method unit tests ──────────────────────────────────────────────


class TestInboundQueueDb:
    @pytest.mark.asyncio
    async def test_enqueue_basic(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound(
            session_id="sess-1",
            origin="telegram",
            content="hello",
            message_type="text",
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_enqueue_dedup_returns_none(self, test_db: Db) -> None:
        row_id1 = await test_db.enqueue_inbound(
            session_id="sess-dedup",
            origin="telegram",
            content="msg1",
            message_type="text",
            source_message_id="msg-100",
        )
        assert row_id1 is not None

        # Same origin + source_message_id → dedup skip
        row_id2 = await test_db.enqueue_inbound(
            session_id="sess-dedup",
            origin="telegram",
            content="msg1-duplicate",
            message_type="text",
            source_message_id="msg-100",
        )
        assert row_id2 is None

    @pytest.mark.asyncio
    async def test_enqueue_different_origins_not_deduped(self, test_db: Db) -> None:
        r1 = await test_db.enqueue_inbound(
            session_id="sess-d2",
            origin="telegram",
            content="msg",
            message_type="text",
            source_message_id="msg-200",
        )
        r2 = await test_db.enqueue_inbound(
            session_id="sess-d2",
            origin="discord",  # different origin
            content="msg",
            message_type="text",
            source_message_id="msg-200",
        )
        assert r1 is not None
        assert r2 is not None

    @pytest.mark.asyncio
    async def test_claim_returns_true_on_success(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound(
            session_id="sess-claim",
            origin="telegram",
            content="hello",
            message_type="text",
        )
        assert row_id is not None
        claimed = await test_db.claim_inbound(row_id, _now(), _past())
        assert claimed is True

    @pytest.mark.asyncio
    async def test_claim_cas_contention_returns_false(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound(
            session_id="sess-cas",
            origin="telegram",
            content="hello",
            message_type="text",
        )
        assert row_id is not None
        # First claim succeeds
        claimed1 = await test_db.claim_inbound(row_id, _now(), _past())
        assert claimed1 is True
        # Second claim fails (row is now "processing" and locked_at is recent, not past cutoff)
        claimed2 = await test_db.claim_inbound(row_id, _now(), _past())
        assert claimed2 is False

    @pytest.mark.asyncio
    async def test_mark_inbound_delivered(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound(
            session_id="sess-del",
            origin="telegram",
            content="hello",
            message_type="text",
        )
        assert row_id is not None
        now = _now()
        await test_db.claim_inbound(row_id, now, _past())
        await test_db.mark_inbound_delivered(row_id, _now())

        # Row should no longer appear in pending fetch
        rows = await test_db.fetch_inbound_pending("sess-del", 10, _now(), _past())
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_mark_inbound_failed_schedules_retry(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound(
            session_id="sess-fail",
            origin="telegram",
            content="hello",
            message_type="text",
        )
        assert row_id is not None
        await test_db.claim_inbound(row_id, _now(), _past())
        await test_db.mark_inbound_failed(row_id, "tmux error", _now(), backoff_seconds=60)

        # Not available now (next_retry_at is in the future)
        rows_now = await test_db.fetch_inbound_pending("sess-fail", 10, _now(), _past())
        assert len(rows_now) == 0

        # Available in far future
        rows_future = await test_db.fetch_inbound_pending("sess-fail", 10, _future(120), _past())
        assert len(rows_future) == 1
        assert rows_future[0]["last_error"] == "tmux error"
        assert rows_future[0]["attempt_count"] == 1

    @pytest.mark.asyncio
    async def test_fetch_inbound_pending_returns_fifo_order(self, test_db: Db) -> None:
        id1 = await test_db.enqueue_inbound("sess-fifo", "tg", "first", message_type="text")
        id2 = await test_db.enqueue_inbound("sess-fifo", "tg", "second", message_type="text")
        id3 = await test_db.enqueue_inbound("sess-fifo", "tg", "third", message_type="text")

        rows = await test_db.fetch_inbound_pending("sess-fifo", 10, _now(), _past())
        assert len(rows) == 3
        assert [r["id"] for r in rows] == [id1, id2, id3]

    @pytest.mark.asyncio
    async def test_fetch_inbound_pending_respects_status_filter(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound("sess-status", "tg", "msg", message_type="text")
        assert row_id is not None
        # Claim and mark delivered
        await test_db.claim_inbound(row_id, _now(), _past())
        await test_db.mark_inbound_delivered(row_id, _now())

        rows = await test_db.fetch_inbound_pending("sess-status", 10, _now(), _past())
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_fetch_respects_lock_cutoff(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound("sess-lock", "tg", "msg", message_type="text")
        assert row_id is not None
        # Claim with a recent timestamp (row is locked with status=processing)
        await test_db.claim_inbound(row_id, _now(), _past())

        # Row is in "processing" status — fetch_inbound_pending only returns pending/failed
        rows = await test_db.fetch_inbound_pending("sess-lock", 10, _now(), _past())
        assert all(r["id"] != row_id for r in rows)

    @pytest.mark.asyncio
    async def test_expired_row_not_returned_by_fetch(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound("sess-exp-fetch", "tg", "msg", message_type="text")
        assert row_id is not None
        await test_db.expire_inbound_for_session("sess-exp-fetch", _now())

        rows = await test_db.fetch_inbound_pending("sess-exp-fetch", 10, _now(), _past())
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_expire_inbound_for_session(self, test_db: Db) -> None:
        await test_db.enqueue_inbound("sess-exp", "tg", "msg1", message_type="text")
        await test_db.enqueue_inbound("sess-exp", "tg", "msg2", message_type="text")

        count = await test_db.expire_inbound_for_session("sess-exp", _now())
        assert count == 2

        rows = await test_db.fetch_inbound_pending("sess-exp", 10, _now(), _past())
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_fetch_sessions_with_pending_inbound(self, test_db: Db) -> None:
        await test_db.enqueue_inbound("sess-a", "tg", "msg", message_type="text")
        await test_db.enqueue_inbound("sess-b", "tg", "msg", message_type="text")

        sessions = await test_db.fetch_sessions_with_pending_inbound()
        assert "sess-a" in sessions
        assert "sess-b" in sessions

    @pytest.mark.asyncio
    async def test_cleanup_inbound_deletes_old_delivered(self, test_db: Db) -> None:
        row_id = await test_db.enqueue_inbound("sess-clean", "tg", "msg", message_type="text")
        assert row_id is not None
        # Mark as delivered
        await test_db.claim_inbound(row_id, _now(), _past())
        await test_db.mark_inbound_delivered(row_id, _now())

        # Threshold far in the future: all delivered rows (regardless of age) are eligible
        deleted = await test_db.cleanup_inbound(_future(60))
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_cleanup_inbound_preserves_pending(self, test_db: Db) -> None:
        await test_db.enqueue_inbound("sess-clean2", "tg", "pending", message_type="text")

        # Threshold far in future — but pending rows are NOT cleaned up (wrong status)
        deleted = await test_db.cleanup_inbound(_future(60))
        assert deleted == 0

        rows = await test_db.fetch_inbound_pending("sess-clean2", 10, _now(), _past())
        assert len(rows) == 1


# ── InboundQueueManager unit tests ───────────────────────────────────


class TestInboundQueueManager:
    @pytest.fixture(autouse=True)
    def _isolated_singleton(self) -> Any:
        """Start with a clean manager; restore the original after each test."""
        import teleclaude.core.inbound_queue as iq_module

        original = iq_module._manager
        iq_module._manager = None
        yield
        iq_module._manager = original

    @pytest.mark.asyncio
    async def test_enqueue_triggers_worker(self, test_db: Db) -> None:
        deliveries: list[InboundQueueRow] = []

        async def deliver(row: InboundQueueRow) -> None:
            deliveries.append(row)

        manager = InboundQueueManager(deliver_fn=deliver)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            row_id = await manager.enqueue(
                session_id="sess-w1",
                origin="telegram",
                content="hello",
                message_type="text",
            )
            assert row_id is not None
            assert "sess-w1" in manager._workers
            await asyncio.sleep(0.1)

        await manager.shutdown()

        assert len(deliveries) == 1
        assert deliveries[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_worker_drains_fifo(self, test_db: Db) -> None:
        delivery_order: list[str] = []

        async def deliver(row: InboundQueueRow) -> None:
            delivery_order.append(row["content"])

        manager = InboundQueueManager(deliver_fn=deliver)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            await manager.enqueue("sess-fifo", "tg", "first", message_type="text")
            await manager.enqueue("sess-fifo", "tg", "second", message_type="text")
            await manager.enqueue("sess-fifo", "tg", "third", message_type="text")
            await asyncio.sleep(0.2)

        await manager.shutdown()

        assert delivery_order == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_worker_retries_on_failure(self, test_db: Db) -> None:
        call_count = 0

        async def deliver(row: InboundQueueRow) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient failure")

        manager = InboundQueueManager(deliver_fn=deliver)

        import teleclaude.core.inbound_queue as iq

        orig_schedule = iq._BACKOFF_SCHEDULE
        iq._BACKOFF_SCHEDULE = [0, 0, 0]

        try:
            with patch("teleclaude.core.inbound_queue.db", test_db):
                await manager.enqueue("sess-retry", "tg", "retry-me", message_type="text")
                await asyncio.sleep(0.3)
        finally:
            iq._BACKOFF_SCHEDULE = orig_schedule

        await manager.shutdown()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_worker_self_terminates_on_empty_queue(self, test_db: Db) -> None:
        async def deliver(row: InboundQueueRow) -> None:
            pass

        manager = InboundQueueManager(deliver_fn=deliver)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            await manager.enqueue("sess-selfterm", "tg", "msg", message_type="text")
            await asyncio.sleep(0.15)
            # Worker should have removed itself from registry after draining
            assert "sess-selfterm" not in manager._workers

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_session_expiry_cancels_worker(self, test_db: Db) -> None:
        started = asyncio.Event()
        blocker = asyncio.Event()

        async def deliver(row: InboundQueueRow) -> None:
            started.set()
            await blocker.wait()  # block until explicitly released

        manager = InboundQueueManager(deliver_fn=deliver)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            await manager.enqueue("sess-expire", "tg", "block me", message_type="text")
            await asyncio.wait_for(started.wait(), timeout=2.0)
            assert "sess-expire" in manager._workers

            await manager.expire_session("sess-expire")
            assert "sess-expire" not in manager._workers

        blocker.set()
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_typing_callback_fired_on_enqueue(self, test_db: Db) -> None:
        typing_calls: list[tuple[str, str]] = []

        async def on_typing(session_id: str, origin: str) -> None:
            typing_calls.append((session_id, origin))

        async def deliver(row: InboundQueueRow) -> None:
            pass

        manager = InboundQueueManager(deliver_fn=deliver, typing_callback=on_typing)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            await manager.enqueue("sess-type", "discord", "hello", message_type="text")
            await asyncio.sleep(0.1)

        await manager.shutdown()

        assert len(typing_calls) == 1
        assert typing_calls[0] == ("sess-type", "discord")

    @pytest.mark.asyncio
    async def test_dedup_skips_typing_callback(self, test_db: Db) -> None:
        typing_calls: list[tuple[str, str]] = []

        async def on_typing(session_id: str, origin: str) -> None:
            typing_calls.append((session_id, origin))

        async def deliver(row: InboundQueueRow) -> None:
            pass

        manager = InboundQueueManager(deliver_fn=deliver, typing_callback=on_typing)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            await manager.enqueue("sess-dedup-type", "tg", "hello", message_type="text", source_message_id="dup-1")
            result = await manager.enqueue(
                "sess-dedup-type", "tg", "hello", message_type="text", source_message_id="dup-1"
            )
            assert result is None
            await asyncio.sleep(0.05)

        await manager.shutdown()

        # Typing callback called only for the first enqueue
        assert len(typing_calls) == 1


# ── Integration tests ─────────────────────────────────────────────────


class TestInboundQueueIntegration:
    @pytest.fixture(autouse=True)
    def _isolated_singleton(self) -> Any:
        """Start with a clean manager; restore the original after each test."""
        import teleclaude.core.inbound_queue as iq_module

        original = iq_module._manager
        iq_module._manager = None
        yield
        iq_module._manager = original

    @pytest.mark.asyncio
    async def test_message_delivered_end_to_end(self, test_db: Db) -> None:
        """Message enqueued → worker delivers → marked delivered."""
        delivered: list[InboundQueueRow] = []

        async def deliver(row: InboundQueueRow) -> None:
            delivered.append(row)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            manager = init_inbound_queue_manager(deliver)
            await manager.enqueue("sess-e2e", "tg", "end-to-end", message_type="text")
            await asyncio.sleep(0.15)
            await manager.shutdown()

        assert len(delivered) == 1
        assert delivered[0]["content"] == "end-to-end"

        # Row should be marked delivered in DB
        rows = await test_db.fetch_inbound_pending("sess-e2e", 10, _now(), _past())
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_delivery_fails_then_retries(self, test_db: Db) -> None:
        """Delivery fails first time, succeeds on retry."""
        attempts: list[int] = []

        async def deliver(row: InboundQueueRow) -> None:
            attempts.append(row["attempt_count"])
            if len(attempts) < 2:
                raise RuntimeError("fail once")

        import teleclaude.core.inbound_queue as iq_module

        orig_schedule = iq_module._BACKOFF_SCHEDULE
        iq_module._BACKOFF_SCHEDULE = [0, 0, 0]

        try:
            with patch("teleclaude.core.inbound_queue.db", test_db):
                manager = init_inbound_queue_manager(deliver)
                await manager.enqueue("sess-retry2", "tg", "retry-msg", message_type="text")
                await asyncio.sleep(0.3)
                await manager.shutdown()
        finally:
            iq_module._BACKOFF_SCHEDULE = orig_schedule

        assert len(attempts) >= 2

    @pytest.mark.asyncio
    async def test_duplicate_source_message_id_deduped(self, test_db: Db) -> None:
        """Second enqueue with same (origin, source_message_id) is a no-op."""
        delivered: list[InboundQueueRow] = []

        async def deliver(row: InboundQueueRow) -> None:
            delivered.append(row)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            manager = init_inbound_queue_manager(deliver)
            r1 = await manager.enqueue(
                "sess-dedup2", "discord", "hello", message_type="text", source_message_id="msg-xyz"
            )
            r2 = await manager.enqueue(
                "sess-dedup2", "discord", "hello", message_type="text", source_message_id="msg-xyz"
            )
            await asyncio.sleep(0.15)
            await manager.shutdown()

        assert r1 is not None
        assert r2 is None
        assert len(delivered) == 1

    @pytest.mark.asyncio
    async def test_session_close_expires_pending(self, test_db: Db) -> None:
        """Session close expires all pending messages."""
        blocker = asyncio.Event()
        delivered: list[InboundQueueRow] = []

        async def deliver(row: InboundQueueRow) -> None:
            await blocker.wait()
            delivered.append(row)

        with patch("teleclaude.core.inbound_queue.db", test_db):
            manager = init_inbound_queue_manager(deliver)
            await manager.enqueue("sess-close", "tg", "never deliver", message_type="text")
            await asyncio.sleep(0.05)
            await manager.expire_session("sess-close")
            blocker.set()
            await manager.shutdown()

        assert len(delivered) == 0
        rows = await test_db.fetch_inbound_pending("sess-close", 10, _now(), _past())
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_startup_resumes_pending_workers(self, test_db: Db) -> None:
        """startup() spawns workers for sessions with pending messages."""
        delivered: list[InboundQueueRow] = []

        async def deliver(row: InboundQueueRow) -> None:
            delivered.append(row)

        # Pre-seed the queue without a manager (simulates messages left over from prior run)
        await test_db.enqueue_inbound("sess-startup", "tg", "pending", message_type="text")

        with patch("teleclaude.core.inbound_queue.db", test_db):
            manager = InboundQueueManager(deliver_fn=deliver)
            await manager.startup()
            await asyncio.sleep(0.15)
            await manager.shutdown()

        assert len(delivered) == 1
        assert delivered[0]["content"] == "pending"


# ── Backoff helper unit tests ─────────────────────────────────────────


class TestBackoffHelper:
    def test_first_attempt(self) -> None:
        assert _backoff_for_attempt(0) == 5.0

    def test_second_attempt(self) -> None:
        assert _backoff_for_attempt(1) == 10.0

    def test_caps_at_last_element(self) -> None:
        assert _backoff_for_attempt(100) == 300.0

    def test_schedule_is_monotone(self) -> None:
        values = [_backoff_for_attempt(i) for i in range(10)]
        assert all(values[i] <= values[i + 1] for i in range(len(values) - 1))
