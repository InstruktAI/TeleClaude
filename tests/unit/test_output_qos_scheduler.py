"""Unit tests for adapter output QoS scheduler."""

import asyncio

import pytest

from teleclaude.adapters.qos.output_scheduler import OutputScheduler
from teleclaude.adapters.qos.policy import OutputPriority, TelegramOutputPolicy


@pytest.mark.asyncio
async def test_telegram_cadence_math_uses_budget_formula_and_rounding() -> None:
    """Strict Telegram policy should derive rounded cadence from configured budget."""
    policy = TelegramOutputPolicy(
        enabled=True,
        group_mpm=20,
        output_budget_ratio=0.8,
        reserve_mpm=4,
        min_session_tick_s=3.0,
        max_session_tick_s=None,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.2,
        rounding_ms=100,
    )

    cadence = policy.compute_cadence(active_emitting_sessions=10, smoothed_active_emitters=10.0)

    assert cadence.effective_output_mpm == 16
    assert cadence.global_tick_s == 3.8
    assert cadence.session_tick_s == 38.0


@pytest.mark.asyncio
async def test_scheduler_coalesces_latest_payload_per_session() -> None:
    """Normal-priority updates should be latest-only while waiting for next slot."""
    policy = TelegramOutputPolicy(
        enabled=True,
        group_mpm=600,
        output_budget_ratio=1.0,
        reserve_mpm=0,
        min_session_tick_s=0.05,
        max_session_tick_s=None,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.2,
        rounding_ms=10,
    )
    scheduler = OutputScheduler(adapter_key="telegram", policy=policy)
    calls: list[str] = []

    async def _dispatch(tag: str) -> str:
        calls.append(tag)
        return tag

    try:
        await scheduler.submit("s1", OutputPriority.NORMAL, lambda: _dispatch("seed"))
        await scheduler.submit("s1", OutputPriority.NORMAL, lambda: _dispatch("stale"))
        await scheduler.submit("s1", OutputPriority.NORMAL, lambda: _dispatch("latest"))

        await asyncio.sleep(0.45)

        assert calls == ["seed", "latest"]
        assert scheduler.snapshot().superseded_payloads == 1
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_high_priority_jumps_ahead_of_normal_queue() -> None:
    """Final/completion updates should dispatch before queued normal updates."""
    policy = TelegramOutputPolicy(
        enabled=True,
        group_mpm=600,
        output_budget_ratio=1.0,
        reserve_mpm=0,
        min_session_tick_s=0.05,
        max_session_tick_s=None,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.2,
        rounding_ms=10,
    )
    scheduler = OutputScheduler(adapter_key="telegram", policy=policy)
    calls: list[str] = []

    async def _dispatch(tag: str) -> str:
        calls.append(tag)
        return tag

    try:
        await scheduler.submit("s1", OutputPriority.NORMAL, lambda: _dispatch("seed"))
        await scheduler.submit("s1", OutputPriority.NORMAL, lambda: _dispatch("normal"))
        await scheduler.submit("s1", OutputPriority.HIGH, lambda: _dispatch("final"))

        await asyncio.sleep(0.5)

        assert calls[:3] == ["seed", "final", "normal"]
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_fairness_prevents_single_session_starvation() -> None:
    """Strict scheduler should dispatch pending updates across active sessions."""
    policy = TelegramOutputPolicy(
        enabled=True,
        group_mpm=600,
        output_budget_ratio=1.0,
        reserve_mpm=0,
        min_session_tick_s=0.1,
        max_session_tick_s=None,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.2,
        rounding_ms=100,
    )
    scheduler = OutputScheduler(adapter_key="telegram", policy=policy)
    calls: list[str] = []

    async def _dispatch(tag: str) -> str:
        calls.append(tag)
        return tag

    try:
        sessions = ["s1", "s2", "s3"]
        for session_id in sessions:
            await scheduler.submit(session_id, OutputPriority.NORMAL, lambda sid=session_id: _dispatch(f"seed:{sid}"))

        for session_id in sessions:
            await scheduler.submit(
                session_id,
                OutputPriority.NORMAL,
                lambda sid=session_id: _dispatch(f"burst:{sid}"),
            )

        await asyncio.sleep(0.8)

        burst_sessions = {call.split(":", 1)[1] for call in calls if call.startswith("burst:")}
        assert burst_sessions == set(sessions)
    finally:
        await scheduler.stop()
