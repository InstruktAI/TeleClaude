"""Unit tests for IngestScheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude_events.signal.scheduler import IngestScheduler


def _make_cartridge(pull_return: int = 3) -> MagicMock:
    cartridge = MagicMock()
    cartridge.pull = AsyncMock(return_value=pull_return)
    return cartridge


def _make_context() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_shutdown_event_stops_loop() -> None:
    """Scheduler exits cleanly when shutdown_event is set before first pull."""
    cartridge = _make_cartridge()
    context = _make_context()
    scheduler = IngestScheduler(cartridge, context, interval_seconds=60)
    shutdown = asyncio.Event()
    shutdown.set()

    await asyncio.wait_for(scheduler.run(shutdown), timeout=1.0)

    cartridge.pull.assert_not_called()


@pytest.mark.asyncio
async def test_pull_executes_after_interval() -> None:
    """Scheduler calls pull once after the interval elapses."""
    cartridge = _make_cartridge()
    context = _make_context()
    scheduler = IngestScheduler(cartridge, context, interval_seconds=0)
    shutdown = asyncio.Event()

    async def _stop_after_pull(*_args: object, **_kwargs: object) -> int:
        shutdown.set()
        return 5

    cartridge.pull = AsyncMock(side_effect=_stop_after_pull)

    await asyncio.wait_for(scheduler.run(shutdown), timeout=2.0)

    cartridge.pull.assert_called_once()


@pytest.mark.asyncio
async def test_pull_exception_does_not_kill_loop() -> None:
    """A pull failure is logged and the loop continues."""
    call_count = 0

    async def _fail_then_stop(context: object) -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient pull error")
        shutdown.set()
        return 0

    cartridge = MagicMock()
    cartridge.pull = AsyncMock(side_effect=_fail_then_stop)
    context = _make_context()
    scheduler = IngestScheduler(cartridge, context, interval_seconds=0)
    shutdown = asyncio.Event()

    await asyncio.wait_for(scheduler.run(shutdown), timeout=2.0)

    assert call_count == 2


@pytest.mark.asyncio
async def test_cancelled_error_propagates() -> None:
    """CancelledError from pull propagates out of the scheduler."""
    async def _raise_cancelled(context: object) -> int:
        raise asyncio.CancelledError()

    cartridge = MagicMock()
    cartridge.pull = AsyncMock(side_effect=_raise_cancelled)
    context = _make_context()
    scheduler = IngestScheduler(cartridge, context, interval_seconds=0)
    shutdown = asyncio.Event()

    with pytest.raises(asyncio.CancelledError):
        await scheduler.run(shutdown)
