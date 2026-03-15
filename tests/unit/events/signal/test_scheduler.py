"""Characterization tests for teleclaude.events.signal.scheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from teleclaude.events.signal.scheduler import IngestScheduler


async def test_scheduler_calls_pull_once_before_shutdown() -> None:
    cartridge = MagicMock()
    cartridge.pull = AsyncMock(return_value=3)
    context = MagicMock()

    scheduler = IngestScheduler(cartridge=cartridge, context=context, interval_seconds=0)
    shutdown = asyncio.Event()

    async def _stop_after_one_pull() -> None:
        # Wait for one pull to happen then shut down
        await asyncio.sleep(0.05)
        shutdown.set()

    await asyncio.gather(
        scheduler.run(shutdown),
        _stop_after_one_pull(),
    )

    cartridge.pull.assert_awaited()


async def test_scheduler_stops_immediately_when_shutdown_set_upfront() -> None:
    cartridge = MagicMock()
    cartridge.pull = AsyncMock(return_value=0)
    context = MagicMock()

    scheduler = IngestScheduler(cartridge=cartridge, context=context, interval_seconds=100)
    shutdown = asyncio.Event()
    shutdown.set()  # pre-set

    await scheduler.run(shutdown)

    cartridge.pull.assert_not_awaited()


async def test_scheduler_swallows_pull_exceptions_and_continues() -> None:
    cartridge = MagicMock()
    call_count = 0

    async def _flaky_pull(*_args: object) -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient failure")
        return 5

    cartridge.pull = _flaky_pull
    context = MagicMock()
    scheduler = IngestScheduler(cartridge=cartridge, context=context, interval_seconds=0)
    shutdown = asyncio.Event()

    async def _stop_after_two_pulls() -> None:
        while call_count < 2:
            await asyncio.sleep(0.01)
        shutdown.set()

    await asyncio.gather(
        scheduler.run(shutdown),
        _stop_after_two_pulls(),
    )

    assert call_count >= 2
