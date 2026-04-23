"""Characterization tests for teleclaude.core.inbound_queue."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.db._rows import InboundQueueRow
from teleclaude.core.inbound_queue import (
    _BACKOFF_SCHEDULE,
    InboundQueueManager,
    _backoff_for_attempt,
    get_inbound_queue_manager,
    init_inbound_queue_manager,
    reset_inbound_queue_manager,
)


class TestBackoffForAttempt:
    @pytest.mark.unit
    def test_attempt_zero_returns_first_value(self):
        result = _backoff_for_attempt(0)
        assert result > 0

    @pytest.mark.unit
    def test_backoff_increases_with_attempts(self):
        b0 = _backoff_for_attempt(0)
        b1 = _backoff_for_attempt(1)
        b2 = _backoff_for_attempt(2)
        assert b0 <= b1 <= b2

    @pytest.mark.unit
    def test_large_attempt_capped_at_max(self):
        b_large = _backoff_for_attempt(1000)
        b_cap = _backoff_for_attempt(6)  # Last index in schedule
        assert b_large == b_cap


class TestInboundQueueManagerSingleton:
    @pytest.mark.unit
    def test_get_before_init_raises(self):
        reset_inbound_queue_manager()
        with pytest.raises(RuntimeError):
            get_inbound_queue_manager()

    @pytest.mark.unit
    def test_init_returns_manager(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        manager = init_inbound_queue_manager(deliver_fn)
        assert isinstance(manager, InboundQueueManager)
        reset_inbound_queue_manager()

    @pytest.mark.unit
    def test_double_init_without_force_raises(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        init_inbound_queue_manager(deliver_fn)
        with pytest.raises(RuntimeError):
            init_inbound_queue_manager(deliver_fn)
        reset_inbound_queue_manager()

    @pytest.mark.unit
    def test_double_init_with_force_succeeds(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        init_inbound_queue_manager(deliver_fn)
        manager = init_inbound_queue_manager(deliver_fn, force=True)
        assert manager is not None
        reset_inbound_queue_manager()

    @pytest.mark.unit
    def test_get_after_init_returns_manager(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        init_inbound_queue_manager(deliver_fn)
        manager = get_inbound_queue_manager()
        assert isinstance(manager, InboundQueueManager)
        reset_inbound_queue_manager()


def _make_row(*, attempt_count: int = 0) -> InboundQueueRow:
    """Build a minimal InboundQueueRow for worker loop tests."""
    return InboundQueueRow(
        id=1,
        session_id="sess-1",
        origin="test",
        message_type="text",
        content="hello",
        payload_json=None,
        actor_id=None,
        actor_name=None,
        actor_avatar_url=None,
        status="pending",
        created_at="2026-01-01T00:00:00+00:00",
        attempt_count=attempt_count,
        next_retry_at=None,
        last_error=None,
        source_message_id=None,
        source_channel_id=None,
    )


class TestWorkerBackoffRegression:
    """Regression tests for the backoff sleep cap bug.

    The old code used ``min(backoff, 5.0)`` which caused the worker to wake
    before next_retry_at expired, see an empty queue, and self-terminate —
    stranding messages permanently after attempt 2.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_worker_sleeps_full_backoff_and_retries_after_failure(self) -> None:
        """After a delivery failure with backoff > 5s, the worker sleeps the full
        backoff (not capped) and retries successfully on the next loop iteration."""
        attempt_count = 2  # schedule index 2 → 20s backoff, well above old 5s cap
        expected_backoff = float(_BACKOFF_SCHEDULE[attempt_count])
        assert expected_backoff > 5.0, "test requires backoff above old cap"

        row = _make_row(attempt_count=attempt_count)
        deliver_fn = AsyncMock(side_effect=[RuntimeError("transient"), None])
        manager = InboundQueueManager(deliver_fn=deliver_fn)

        sleep_durations: list[float] = []

        with patch("teleclaude.core.inbound_queue.db") as mock_db:
            # First fetch: return the row (will fail delivery)
            # Second fetch: return the row again (retry succeeds)
            # Third fetch: empty queue → worker exits cleanly
            mock_db.fetch_inbound_pending = AsyncMock(side_effect=[[row], [row], []])
            mock_db.claim_inbound = AsyncMock(return_value=True)
            mock_db.mark_inbound_failed = AsyncMock()
            mock_db.mark_inbound_delivered = AsyncMock()

            mock_sleep = AsyncMock(side_effect=lambda d: sleep_durations.append(d))
            with patch("asyncio.sleep", mock_sleep):
                await manager._worker_loop("sess-1")

        assert sleep_durations == [expected_backoff]
        assert deliver_fn.call_count == 2
        mock_db.mark_inbound_delivered.assert_called_once()
