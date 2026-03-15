"""Characterization tests for teleclaude.adapters.qos.output_scheduler."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler, QoSPayload, _ceil_to_ms
from teleclaude.adapters.qos.policy import QoSPolicy

# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _policy(mode: str = "off", group_mpm: int = 20, rounding_ms: int = 100) -> QoSPolicy:
    return QoSPolicy(
        adapter_key="test",
        mode=mode,
        group_mpm=group_mpm,
        output_budget_ratio=0.8,
        reserve_mpm=4,
        rounding_ms=rounding_ms,
    )


class TestCeilToMs:
    @pytest.mark.unit
    def test_already_aligned_value_unchanged(self):
        assert _ceil_to_ms(0.5, 100) == pytest.approx(0.5)

    @pytest.mark.unit
    def test_rounds_up_to_granularity(self):
        result = _ceil_to_ms(0.31, 100)
        assert result == pytest.approx(0.4)

    @pytest.mark.unit
    def test_zero_returns_zero(self):
        assert _ceil_to_ms(0.0, 100) == pytest.approx(0.0)


class TestQoSPayload:
    @pytest.mark.unit
    def test_enqueued_at_defaults_to_now(self):
        before = time.monotonic()
        payload = QoSPayload(session_id="s1", factory=AsyncMock())
        after = time.monotonic()
        assert before <= payload.enqueued_at <= after

    @pytest.mark.unit
    def test_is_final_defaults_to_false(self):
        payload = QoSPayload(session_id="s1", factory=AsyncMock())
        assert payload.is_final is False

    @pytest.mark.unit
    def test_custom_is_final(self):
        payload = QoSPayload(session_id="s1", factory=AsyncMock(), is_final=True)
        assert payload.is_final is True


class TestOutputQoSSchedulerLifecycle:
    @pytest.mark.unit
    def test_start_in_off_mode_creates_no_task(self):
        scheduler = OutputQoSScheduler(_policy("off"))
        scheduler.start()
        assert scheduler._task is None

    @pytest.mark.unit
    async def test_start_in_coalesce_mode_creates_task(self):
        scheduler = OutputQoSScheduler(_policy("coalesce_only"))
        scheduler.start()
        assert scheduler._task is not None
        assert not scheduler._task.done()
        await scheduler.stop()

    @pytest.mark.unit
    async def test_stop_cancels_task(self):
        scheduler = OutputQoSScheduler(_policy("coalesce_only"))
        scheduler.start()
        await scheduler.stop()
        assert scheduler._task is None

    @pytest.mark.unit
    async def test_stop_on_off_mode_is_noop(self):
        scheduler = OutputQoSScheduler(_policy("off"))
        # Should not raise
        await scheduler.stop()
        assert scheduler._task is None

    @pytest.mark.unit
    async def test_double_start_does_not_create_second_task(self):
        scheduler = OutputQoSScheduler(_policy("coalesce_only"))
        scheduler.start()
        first_task = scheduler._task
        scheduler.start()
        assert scheduler._task is first_task
        await scheduler.stop()


class TestOutputQoSSchedulerEnqueue:
    @pytest.mark.unit
    def test_non_final_enqueue_stores_in_normal_slots(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock()
        scheduler.enqueue("sess1", factory, is_final=False)
        assert "sess1" in scheduler._normal_slots

    @pytest.mark.unit
    def test_final_enqueue_stores_in_priority_queue(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock()
        scheduler.enqueue("sess1", factory, is_final=True)
        assert "sess1" in scheduler._priority_queues
        assert len(scheduler._priority_queues["sess1"]) == 1

    @pytest.mark.unit
    def test_second_non_final_enqueue_replaces_existing_coalesces(self):
        scheduler = OutputQoSScheduler(_policy())
        f1 = AsyncMock()
        f2 = AsyncMock()
        scheduler.enqueue("sess1", f1)
        scheduler.enqueue("sess1", f2)
        # Only the latest is kept
        assert scheduler._normal_slots["sess1"].factory is f2
        assert scheduler._coalesced == 1

    @pytest.mark.unit
    def test_multiple_final_payloads_all_queued(self):
        scheduler = OutputQoSScheduler(_policy())
        for _ in range(3):
            scheduler.enqueue("sess1", AsyncMock(), is_final=True)
        assert len(scheduler._priority_queues["sess1"]) == 3

    @pytest.mark.unit
    def test_enqueue_adds_session_to_rr_list(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler.enqueue("sess1", AsyncMock())
        assert "sess1" in scheduler._rr_sessions

    @pytest.mark.unit
    def test_enqueue_same_session_twice_not_duplicated_in_rr(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler.enqueue("sess1", AsyncMock())
        scheduler.enqueue("sess1", AsyncMock())
        assert scheduler._rr_sessions.count("sess1") == 1


class TestOutputQoSSchedulerDropPending:
    @pytest.mark.unit
    def test_drop_pending_removes_normal_slot(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler.enqueue("sess1", AsyncMock())
        dropped = scheduler.drop_pending("sess1")
        assert dropped == 1
        assert "sess1" not in scheduler._normal_slots

    @pytest.mark.unit
    def test_drop_pending_no_slot_returns_zero(self):
        scheduler = OutputQoSScheduler(_policy())
        dropped = scheduler.drop_pending("sess1")
        assert dropped == 0

    @pytest.mark.unit
    def test_drop_pending_does_not_affect_priority_queue(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler.enqueue("sess1", AsyncMock(), is_final=True)
        scheduler.enqueue("sess1", AsyncMock())
        scheduler.drop_pending("sess1")
        assert "sess1" in scheduler._priority_queues


class TestOutputQoSSchedulerPickPayload:
    @pytest.mark.unit
    def test_pick_priority_over_normal(self):
        scheduler = OutputQoSScheduler(_policy())
        normal_f = AsyncMock()
        final_f = AsyncMock()
        scheduler.enqueue("sess1", normal_f)
        scheduler.enqueue("sess1", final_f, is_final=True)
        payload = scheduler._pick_payload_for("sess1")
        assert payload is not None
        assert payload.factory is final_f

    @pytest.mark.unit
    def test_pick_normal_when_no_priority(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock()
        scheduler.enqueue("sess1", factory)
        payload = scheduler._pick_payload_for("sess1")
        assert payload is not None
        assert payload.factory is factory

    @pytest.mark.unit
    def test_pick_removes_priority_queue_when_empty(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler.enqueue("sess1", AsyncMock(), is_final=True)
        scheduler._pick_payload_for("sess1")
        assert "sess1" not in scheduler._priority_queues


class TestOutputQoSSchedulerComputeTick:
    @pytest.mark.unit
    def test_coalesce_mode_tick_equals_rounding_ms(self):
        scheduler = OutputQoSScheduler(_policy("coalesce_only", rounding_ms=250))
        tick = scheduler._compute_tick_s()
        assert tick == pytest.approx(0.25)

    @pytest.mark.unit
    def test_strict_mode_tick_derived_from_budget(self):
        # group_mpm=20, reserve_mpm=4, output_budget_ratio=0.8
        # effective_mpm = min(20-4, floor(20*0.8)) = min(16, 16) = 16
        # global_tick_s = ceil_to_ms(60/16, 100) = ceil_to_ms(3.75, 100) = 3.8
        scheduler = OutputQoSScheduler(_policy("strict", group_mpm=20, rounding_ms=100))
        tick = scheduler._compute_tick_s()
        assert tick == pytest.approx(3.8)


class TestOutputQoSSchedulerComputeActiveCount:
    @pytest.mark.unit
    def test_empty_scheduler_has_zero_active(self):
        scheduler = OutputQoSScheduler(_policy())
        assert scheduler._compute_active_count() == 0.0

    @pytest.mark.unit
    def test_pending_session_counted(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler.enqueue("sess1", AsyncMock())
        assert scheduler._compute_active_count() == 1.0

    @pytest.mark.unit
    def test_recently_dispatched_session_counted(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler._active_emitters["sess2"] = time.monotonic()
        assert scheduler._compute_active_count() == 1.0


class TestOutputQoSSchedulerUpdateEma:
    @pytest.mark.unit
    def test_ema_initialises_from_zero_to_raw(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler._update_ema(5.0)
        assert scheduler._ema_session_count == 5.0

    @pytest.mark.unit
    def test_ema_smooths_subsequent_updates(self):
        scheduler = OutputQoSScheduler(_policy())
        scheduler._update_ema(10.0)
        scheduler._update_ema(0.0)
        # alpha=0.2: 0.2*0 + 0.8*10 = 8.0
        assert scheduler._ema_session_count == pytest.approx(8.0)


class TestOutputQoSSchedulerExecute:
    @pytest.mark.unit
    async def test_execute_calls_factory(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock(return_value="msg-123")
        payload = QoSPayload(session_id="sess1", factory=factory)
        await scheduler._execute(payload)
        factory.assert_awaited_once()

    @pytest.mark.unit
    async def test_execute_updates_active_emitters(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock(return_value=None)
        payload = QoSPayload(session_id="sess1", factory=factory)
        await scheduler._execute(payload)
        assert "sess1" in scheduler._active_emitters

    @pytest.mark.unit
    async def test_execute_increments_dispatched_counter(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock(return_value=None)
        payload = QoSPayload(session_id="sess1", factory=factory)
        await scheduler._execute(payload)
        assert scheduler._dispatched == 1

    @pytest.mark.unit
    async def test_execute_increments_error_counter_on_exception(self):
        scheduler = OutputQoSScheduler(_policy())
        factory = AsyncMock(side_effect=RuntimeError("boom"))
        payload = QoSPayload(session_id="sess1", factory=factory)
        await scheduler._execute(payload)
        assert scheduler._dispatch_errors == 1
        assert scheduler._dispatched == 0
