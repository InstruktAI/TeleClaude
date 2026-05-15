"""Debounced, cancelable per-session-per-event slow-work scheduler.

The hook outbox FIFO drain must stay fast. LLM, TTS, and similar
network-bound work that takes seconds cannot run inline inside it without
blocking every subsequent event for the same session.

This module provides one primitive — ``schedule`` — that registers a
debounced runner under a ``(session_id, event_type)`` key. A second
``schedule`` call for the same key while a prior task is still pending (in
the debounce window or already executing) cancels it and starts a fresh
debounce window. Different event types on the same session occupy distinct
slots and never cancel each other.

Cancellation rationale: a new event on the same slot guarantees the prior
run's output will be superseded. Letting the in-flight work finish wastes
LLM tokens and TTS bandwidth. ``task.cancel()`` propagates through
``await`` points; the runner is expected to use streaming network calls so
that connection abort signals provider-side generation to stop.

Runners must read fresh state at execution time and must tolerate
``asyncio.CancelledError`` by exiting cleanly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_DEBOUNCE_S: float = 1.0

_pending: dict[tuple[str, str], asyncio.Task[None]] = {}


def schedule(
    *,
    session_id: str,
    event_type: str,
    runner: Callable[[], Awaitable[None]],
    debounce_s: float | None = None,
) -> None:
    """Schedule ``runner`` to execute after ``debounce_s`` seconds of quiet.

    A subsequent call for the same ``(session_id, event_type)`` slot
    cancels the prior task — whether it is still in the debounce window or
    already inside ``runner`` — and starts a fresh debounce timer.
    """
    key = (session_id, event_type)
    existing = _pending.pop(key, None)
    if existing is not None and not existing.done():
        existing.cancel()

    task: asyncio.Task[None]

    async def _wait_then_run() -> None:
        # Resolve the debounce window at call time so tests can monkeypatch
        # _DEFAULT_DEBOUNCE_S without timing out on the production default.
        sleep_s = _DEFAULT_DEBOUNCE_S if debounce_s is None else debounce_s
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            return
        try:
            await runner()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(
                "slow work runner failed",
                session_id=session_id,
                event_type=event_type,
                error=str(exc),
            )
        finally:
            current = _pending.get(key)
            if current is task:
                _pending.pop(key, None)

    task = asyncio.create_task(_wait_then_run(), name=f"slow-{event_type}-{session_id}")
    _pending[key] = task


def pending_count() -> int:
    """Return current number of pending slow-work tasks (for diagnostics)."""
    return sum(1 for task in _pending.values() if not task.done())
