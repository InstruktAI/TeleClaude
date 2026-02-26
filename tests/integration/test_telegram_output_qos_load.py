"""Integration-style load checks for Telegram output QoS scheduler."""

import asyncio

import pytest

from teleclaude.adapters.qos.output_scheduler import OutputScheduler
from teleclaude.adapters.qos.policy import OutputPriority, TelegramOutputPolicy


@pytest.mark.asyncio
async def test_qos_scheduler_stabilizes_queue_for_20_active_sessions() -> None:
    """Under bursty load, latest-only coalescing should keep queue bounded."""
    policy = TelegramOutputPolicy(
        enabled=True,
        group_mpm=120,
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
        session_ids = [f"s{idx}" for idx in range(20)]

        for step in range(8):
            for session_id in session_ids:
                await scheduler.submit(
                    session_id,
                    OutputPriority.NORMAL,
                    lambda sid=session_id, s=step: _dispatch(f"{sid}:{s}"),
                )

        await asyncio.sleep(2.5)

        snapshot = scheduler.snapshot()
        assert snapshot.queue_depth <= len(session_ids)
        assert snapshot.superseded_payloads > 0

        delivered_sessions = {call.split(":", 1)[0] for call in calls}
        assert delivered_sessions == set(session_ids)
    finally:
        await scheduler.stop()
