"""Tests for teleclaude.core.agent_coordinator._slow_work.

The slow-work scheduler decouples LLM/TTS work from the hook-outbox FIFO
drain. Each ``(session_id, event_type)`` slot debounces and supersedes: a
new schedule on the same slot cancels the prior task (whether mid-sleep or
mid-execution) and starts a fresh debounce window. These tests pin that
contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.agent_coordinator import _slow_work


@pytest.fixture(autouse=True)
def _reset_pending() -> Generator[None, None, None]:
    """Ensure the module-level slot registry starts empty for each test."""
    _slow_work._pending.clear()
    yield
    for task in list(_slow_work._pending.values()):
        if not task.done():
            task.cancel()
    _slow_work._pending.clear()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_runs_runner_after_debounce_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One schedule call runs its runner exactly once after the debounce
    window elapses."""
    monkeypatch.setattr(_slow_work, "_DEFAULT_DEBOUNCE_S", 0.05)
    runner = AsyncMock()

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=runner)

    await asyncio.sleep(0.15)

    runner.assert_awaited_once_with()
    assert ("sess-a", "agent_stop") not in _slow_work._pending


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rapid_schedules_coalesce_into_single_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three rapid schedules for the same slot within the debounce window
    collapse to one runner invocation. Each new schedule resets the timer;
    only the latest one's expiry fires."""
    monkeypatch.setattr(_slow_work, "_DEFAULT_DEBOUNCE_S", 0.05)
    runners = [AsyncMock() for _ in range(3)]

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=runners[0])
    await asyncio.sleep(0.01)
    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=runners[1])
    await asyncio.sleep(0.01)
    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=runners[2])

    await asyncio.sleep(0.15)

    runners[0].assert_not_awaited()
    runners[1].assert_not_awaited()
    runners[2].assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedules_for_separate_event_types_run_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different event types on the same session are independent slots;
    scheduling one does not cancel the other."""
    monkeypatch.setattr(_slow_work, "_DEFAULT_DEBOUNCE_S", 0.05)
    stop_runner = AsyncMock()
    start_runner = AsyncMock()

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=stop_runner)
    _slow_work.schedule(session_id="sess-a", event_type="session_start", runner=start_runner)

    await asyncio.sleep(0.15)

    stop_runner.assert_awaited_once_with()
    start_runner.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedules_for_separate_sessions_run_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same event type across different sessions does not cancel across
    sessions."""
    monkeypatch.setattr(_slow_work, "_DEFAULT_DEBOUNCE_S", 0.05)
    runner_a = AsyncMock()
    runner_b = AsyncMock()

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=runner_a)
    _slow_work.schedule(session_id="sess-b", event_type="agent_stop", runner=runner_b)

    await asyncio.sleep(0.15)

    runner_a.assert_awaited_once_with()
    runner_b.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_schedule_cancels_runner_already_executing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new schedule arriving while the prior runner is mid-execution
    cancels that runner. The cancelled runner observes CancelledError and
    exits silently. The new runner runs to completion."""
    monkeypatch.setattr(_slow_work, "_DEFAULT_DEBOUNCE_S", 0.02)

    first_started = asyncio.Event()
    first_was_cancelled = False

    async def first_runner() -> None:
        nonlocal first_was_cancelled
        first_started.set()
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            first_was_cancelled = True
            raise

    second_runner = AsyncMock()

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=first_runner)
    await first_started.wait()

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=second_runner)

    await asyncio.sleep(0.10)

    assert first_was_cancelled
    second_runner.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_exception_does_not_leave_orphaned_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-CancelledError exception inside the runner is contained; the
    slot is cleared so a subsequent schedule starts fresh."""
    monkeypatch.setattr(_slow_work, "_DEFAULT_DEBOUNCE_S", 0.02)

    async def failing_runner() -> None:
        raise RuntimeError("simulated failure")

    _slow_work.schedule(session_id="sess-a", event_type="agent_stop", runner=failing_runner)

    await asyncio.sleep(0.10)

    assert ("sess-a", "agent_stop") not in _slow_work._pending
