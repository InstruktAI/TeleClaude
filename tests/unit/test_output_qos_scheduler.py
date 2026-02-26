"""Unit tests for OutputQoSScheduler: cadence, coalescing, fairness, priority."""

from __future__ import annotations

import asyncio
import math
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler, QoSPayload, _ceil_to_ms
from teleclaude.adapters.qos.policy import QoSPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(mode: str = "strict", group_mpm: int = 20, reserve_mpm: int = 4, rounding_ms: int = 100) -> QoSPolicy:
    return QoSPolicy(
        adapter_key="test",
        mode=mode,
        group_mpm=group_mpm,
        output_budget_ratio=0.8,
        reserve_mpm=reserve_mpm,
        min_session_tick_s=0.1,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.5,
        rounding_ms=rounding_ms,
    )


def _scheduler(mode: str = "strict", **kwargs) -> OutputQoSScheduler:
    return OutputQoSScheduler(_policy(mode=mode, **kwargs))


# ---------------------------------------------------------------------------
# _ceil_to_ms
# ---------------------------------------------------------------------------


def test_ceil_to_ms_exact():
    """Exact multiples are unchanged."""
    assert _ceil_to_ms(0.5, 100) == pytest.approx(0.5)


def test_ceil_to_ms_rounds_up():
    """Non-exact values are rounded up to next 100ms boundary."""
    assert _ceil_to_ms(0.501, 100) == pytest.approx(0.6)


def test_ceil_to_ms_zero():
    assert _ceil_to_ms(0.0, 100) == pytest.approx(0.0)


def test_ceil_to_ms_custom_granularity():
    """250ms rounding."""
    # 0.3s → next 250ms boundary → 0.5s
    assert _ceil_to_ms(0.3, 250) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Tick computation
# ---------------------------------------------------------------------------


def test_compute_tick_s_coalesce_only():
    """coalesce_only mode: tick = rounding_ms / 1000."""
    s = _scheduler(mode="coalesce_only", rounding_ms=200)
    assert s._compute_tick_s() == pytest.approx(0.2)


def test_compute_tick_s_strict_nominal():
    """strict mode: tick derived from effective_mpm.

    group_mpm=20, output_budget_ratio=0.8, reserve_mpm=4:
    effective = max(1, min(20-4, floor(20*0.8))) = max(1, min(16, 16)) = 16
    global_tick_s = ceil_to_100ms(60/16) = ceil_to_100ms(3.75) = 3.8
    """
    s = _scheduler(mode="strict", group_mpm=20, reserve_mpm=4, rounding_ms=100)
    tick = s._compute_tick_s()
    assert tick == pytest.approx(3.8)


def test_compute_tick_s_strict_reserve_larger_than_ratio():
    """reserve_mpm dominates when it leaves fewer mpm than ratio allows.

    group_mpm=20, reserve_mpm=18:
    effective = max(1, min(20-18=2, floor(20*0.8)=16)) = max(1, 2) = 2
    global_tick_s = ceil_to_100ms(60/2=30) = 30.0
    """
    s = _scheduler(mode="strict", group_mpm=20, reserve_mpm=18, rounding_ms=100)
    tick = s._compute_tick_s()
    assert tick == pytest.approx(30.0)


def test_compute_tick_s_strict_clamp_to_one_mpm():
    """When budget is exhausted effective_mpm clamps to 1.

    group_mpm=4, reserve_mpm=4:
    effective = max(1, min(0, floor(4*0.8)=3)) = max(1, 0) = 1
    global_tick_s = ceil_to_100ms(60) = 60.0
    """
    s = _scheduler(mode="strict", group_mpm=4, reserve_mpm=4, rounding_ms=100)
    tick = s._compute_tick_s()
    assert tick == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Enqueue: coalescing (normal slots)
# ---------------------------------------------------------------------------


def test_enqueue_normal_replaces_previous():
    """Enqueueing a second normal payload replaces the first (latest-only)."""
    s = _scheduler()
    calls: list[str] = []

    async def f1() -> Optional[str]:
        calls.append("f1")
        return None

    async def f2() -> Optional[str]:
        calls.append("f2")
        return None

    s.enqueue("sess-a", f1, is_final=False)
    assert "sess-a" in s._normal_slots
    s.enqueue("sess-a", f2, is_final=False)
    assert "sess-a" in s._normal_slots
    # Only one slot remains; coalesced counter incremented.
    assert s._coalesced == 1
    # The slot holds the newer factory.
    assert s._normal_slots["sess-a"].factory is f2


def test_enqueue_normal_multiple_sessions():
    """Each session gets its own slot; no coalescing across sessions."""
    s = _scheduler()

    async def fa() -> Optional[str]:
        return None

    async def fb() -> Optional[str]:
        return None

    s.enqueue("sess-a", fa)
    s.enqueue("sess-b", fb)
    assert len(s._normal_slots) == 2
    assert s._coalesced == 0


# ---------------------------------------------------------------------------
# Enqueue: priority queue (is_final)
# ---------------------------------------------------------------------------


def test_enqueue_final_appends_to_priority_fifo():
    """Final payloads are not coalesced — they queue in FIFO order."""
    s = _scheduler()

    async def f1() -> Optional[str]:
        return "1"

    async def f2() -> Optional[str]:
        return "2"

    s.enqueue("sess-a", f1, is_final=True)
    s.enqueue("sess-a", f2, is_final=True)
    assert len(s._priority_queues["sess-a"]) == 2
    assert s._coalesced == 0


def test_enqueue_final_does_not_replace_normal():
    """is_final=True adds to priority queue; normal slot is unaffected."""
    s = _scheduler()

    async def fn() -> Optional[str]:
        return None

    async def ff() -> Optional[str]:
        return None

    s.enqueue("sess-a", fn, is_final=False)
    s.enqueue("sess-a", ff, is_final=True)
    assert "sess-a" in s._normal_slots
    assert "sess-a" in s._priority_queues
    assert s._normal_slots["sess-a"].factory is fn


# ---------------------------------------------------------------------------
# Round-robin session tracking
# ---------------------------------------------------------------------------


def test_enqueue_adds_to_rr_sessions_once():
    """Each session appears once in the round-robin list regardless of enqueue count."""
    s = _scheduler()

    async def f() -> Optional[str]:
        return None

    s.enqueue("sess-a", f)
    s.enqueue("sess-a", f)
    s.enqueue("sess-b", f)
    assert s._rr_sessions.count("sess-a") == 1
    assert s._rr_sessions.count("sess-b") == 1


# ---------------------------------------------------------------------------
# Dispatch: coalesce_only mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_all_pending_coalesce_only():
    """_dispatch_all_pending dispatches one payload per session."""
    s = _scheduler(mode="coalesce_only")
    dispatched: list[str] = []

    async def fa() -> Optional[str]:
        dispatched.append("a")
        return None

    async def fb() -> Optional[str]:
        dispatched.append("b")
        return None

    s.enqueue("sess-a", fa)
    s.enqueue("sess-b", fb)
    await s._dispatch_all_pending()

    assert set(dispatched) == {"a", "b"}
    assert s._dispatched == 2
    assert not s._normal_slots  # Slots consumed.


@pytest.mark.asyncio
async def test_dispatch_all_pending_priority_first():
    """Priority payloads are dispatched before normal ones per session."""
    s = _scheduler(mode="coalesce_only")
    order: list[str] = []

    async def normal() -> Optional[str]:
        order.append("normal")
        return None

    async def priority() -> Optional[str]:
        order.append("priority")
        return None

    s.enqueue("sess-a", normal, is_final=False)
    s.enqueue("sess-a", priority, is_final=True)
    await s._dispatch_all_pending()

    # Only one payload per session per cycle; priority wins.
    assert order == ["priority"]
    # Normal slot still pending.
    assert "sess-a" in s._normal_slots


# ---------------------------------------------------------------------------
# Dispatch: strict mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_one_priority_before_normal():
    """Priority queue is drained before normal round-robin in strict mode."""
    s = _scheduler(mode="strict")
    order: list[str] = []

    async def normal() -> Optional[str]:
        order.append("normal")
        return None

    async def priority() -> Optional[str]:
        order.append("priority")
        return None

    s.enqueue("sess-a", normal)
    s.enqueue("sess-a", priority, is_final=True)
    await s._dispatch_one()

    assert order == ["priority"]
    assert "sess-a" in s._normal_slots  # Normal still pending.
    assert "sess-a" not in s._priority_queues  # Priority consumed.


@pytest.mark.asyncio
async def test_dispatch_one_round_robin():
    """Strict mode dispatches sessions in round-robin order."""
    s = _scheduler(mode="strict")
    order: list[str] = []

    async def make_fn(label: str):
        async def fn() -> Optional[str]:
            order.append(label)
            return None

        return fn

    s.enqueue("sess-a", await make_fn("a"))
    s.enqueue("sess-b", await make_fn("b"))
    s.enqueue("sess-c", await make_fn("c"))

    await s._dispatch_one()
    await s._dispatch_one()
    await s._dispatch_one()

    assert set(order) == {"a", "b", "c"}
    assert len(order) == 3


@pytest.mark.asyncio
async def test_dispatch_one_no_sessions_noop():
    """_dispatch_one is a no-op when there are no pending payloads."""
    s = _scheduler(mode="strict")
    await s._dispatch_one()
    assert s._dispatched == 0


# ---------------------------------------------------------------------------
# Priority queue cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_queue_removed_when_empty():
    """Priority queue entry for a session is cleaned up after last payload."""
    s = _scheduler(mode="strict")

    async def f() -> Optional[str]:
        return None

    s.enqueue("sess-a", f, is_final=True)
    assert "sess-a" in s._priority_queues
    await s._dispatch_one()
    assert "sess-a" not in s._priority_queues


# ---------------------------------------------------------------------------
# EMA update
# ---------------------------------------------------------------------------


def test_update_ema_initializes_on_zero():
    """First update seeds EMA from raw count directly (not weighted)."""
    s = _scheduler()
    assert s._ema_session_count == 0.0
    s._update_ema(5.0)
    assert s._ema_session_count == pytest.approx(5.0)


def test_update_ema_smooths_subsequent_updates():
    """Subsequent EMA updates apply alpha-weighted blending."""
    s = _scheduler()
    s._update_ema(10.0)  # Initialize to 10.
    # alpha=0.5: ema = 0.5*4 + 0.5*10 = 7.0
    s._update_ema(4.0)
    assert s._ema_session_count == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_error_increments_error_counter():
    """Dispatch errors are counted and do not propagate."""
    s = _scheduler()

    async def boom() -> Optional[str]:
        raise RuntimeError("oops")

    payload = QoSPayload(session_id="sess-err", factory=boom)
    await s._execute(payload)
    assert s._dispatch_errors == 1
    assert s._dispatched == 0


@pytest.mark.asyncio
async def test_execute_success_increments_dispatched():
    """Successful dispatch increments dispatched counter."""
    s = _scheduler()

    async def ok() -> Optional[str]:
        return "msg-id"

    payload = QoSPayload(session_id="sess-ok", factory=ok)
    await s._execute(payload)
    assert s._dispatched == 1
    assert s._dispatch_errors == 0
    assert "sess-ok" in s._active_emitters


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_background_task():
    """start() spawns a background dispatch task for non-off modes."""
    s = _scheduler(mode="coalesce_only")
    s.start()
    assert s._task is not None
    assert not s._task.done()
    await s.stop()


@pytest.mark.asyncio
async def test_start_noop_for_off_mode():
    """start() is a no-op when mode is off."""
    s = _scheduler(mode="off")
    s.start()
    assert s._task is None


@pytest.mark.asyncio
async def test_stop_cancels_task():
    """stop() cancels and awaits the background task."""
    s = _scheduler(mode="strict")
    s.start()
    task = s._task
    await s.stop()
    assert s._task is None
    assert task is not None and task.done()


@pytest.mark.asyncio
async def test_start_idempotent():
    """Calling start() twice does not spawn a second task."""
    s = _scheduler(mode="strict")
    s.start()
    first_task = s._task
    s.start()
    assert s._task is first_task  # Same task.
    await s.stop()


# ---------------------------------------------------------------------------
# Compute active count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_active_count_pending_only():
    """Sessions with pending payloads are counted as active."""
    s = _scheduler()

    async def f() -> Optional[str]:
        return None

    s.enqueue("sess-a", f)
    s.enqueue("sess-b", f, is_final=True)
    count = s._compute_active_count()
    assert count == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_compute_active_count_includes_recent_emitters():
    """Sessions that dispatched within the window are counted as active."""
    s = _scheduler()

    async def f() -> Optional[str]:
        return None

    payload = QoSPayload(session_id="sess-recent", factory=f)
    await s._execute(payload)
    # After dispatch, no pending payloads, but sess-recent is within window.
    count = s._compute_active_count()
    assert count == pytest.approx(1.0)
