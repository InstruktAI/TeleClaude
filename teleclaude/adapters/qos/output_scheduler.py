"""Output QoS scheduler for adapter output coalescing and fairness pacing.

Implements two-layer output QoS:
- Latest-only coalescing: drops superseded non-final payloads per session.
- Fair dispatch: round-robin across active sessions with dynamic cadence derived
  from the configured group budget and the current number of active emitters.

Dispatch modes:
- "off": scheduler is not used; caller delivers output directly.
- "coalesce_only": background loop ticks at rounding_ms intervals; dispatches
  all pending sessions each tick (coalescing within the window, no hard pacing).
- "strict": background loop ticks at computed global_tick_s; dispatches ONE
  session per tick in round-robin order, enforcing the group mpm budget.

Cadence formula (strict mode):
  effective_output_mpm = max(1, min(group_mpm - reserve_mpm,
                                    floor(group_mpm * output_budget_ratio)))
  global_tick_s        = ceil_to_ms(60 / effective_output_mpm, rounding_ms)
  target_session_tick_s = ceil_to_ms(max(min_session_tick_s,
                                          global_tick_s * active_emitting_sessions),
                                      rounding_ms)
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from instrukt_ai_logging import get_logger

from teleclaude.adapters.qos.policy import QoSPolicy

logger = get_logger(__name__)

# Interval for periodic cadence log summaries.
_SUMMARY_INTERVAL_S = 30.0


def _ceil_to_ms(seconds: float, rounding_ms: int) -> float:
    """Round seconds up to the nearest rounding_ms granularity."""
    granularity = rounding_ms / 1000.0
    return math.ceil(seconds / granularity) * granularity


@dataclass
class QoSPayload:
    """A pending output payload waiting for dispatch.

    Attributes:
        session_id: Session this payload belongs to.
        factory: Async callable that performs the actual output delivery.
        is_final: When True, payload goes to priority queue (next available slot).
        enqueued_at: Monotonic time when payload was enqueued (for age logging).
    """

    session_id: str
    factory: Callable[[], Awaitable[Optional[str]]]
    is_final: bool = False
    enqueued_at: float = field(default_factory=time.monotonic)


class OutputQoSScheduler:
    """Per-adapter output scheduler with coalescing and fairness dispatch.

    One instance should be created per adapter. Call start() at adapter startup
    and stop() at adapter shutdown.
    """

    def __init__(self, policy: QoSPolicy) -> None:
        self._policy = policy
        # Normal (non-final) slots: session_id -> latest payload (latest-only).
        self._normal_slots: dict[str, QoSPayload] = {}
        # Priority (final) queue: session_id -> ordered FIFO of payloads.
        self._priority_queues: dict[str, deque[QoSPayload]] = {}
        # Active emitter tracking: session_id -> last dispatch monotonic time.
        self._active_emitters: dict[str, float] = {}
        # EMA-smoothed active session count.
        self._ema_session_count: float = 0.0
        # Round-robin pointer into session order list.
        self._rr_sessions: list[str] = []
        self._rr_idx: int = 0
        # Background dispatch task.
        self._task: asyncio.Task[None] | None = None
        # Stats counters.
        self._coalesced: int = 0
        self._dispatched: int = 0
        self._dispatch_errors: int = 0
        self._last_summary_at: float = time.monotonic()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background dispatch loop."""
        if self._policy.mode == "off":
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._dispatch_loop(), name=f"qos-scheduler-{self._policy.adapter_key}")
        logger.info(
            "OutputQoSScheduler started: adapter=%s mode=%s",
            self._policy.adapter_key,
            self._policy.mode,
        )

    async def stop(self) -> None:
        """Stop the background dispatch loop."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("OutputQoSScheduler stopped: adapter=%s", self._policy.adapter_key)

    # ------------------------------------------------------------------
    # Enqueueing
    # ------------------------------------------------------------------

    def enqueue(self, session_id: str, factory: Callable[[], Awaitable[Optional[str]]], is_final: bool = False) -> None:
        """Enqueue an output payload for the given session.

        For non-final payloads: replaces any existing pending payload (latest-only
        coalescing). For final payloads: appended to the priority FIFO queue.

        Args:
            session_id: Session identifier.
            factory: Async callable that delivers the output when awaited.
            is_final: When True, treat as high-priority (not coalesced away).
        """
        payload = QoSPayload(session_id=session_id, factory=factory, is_final=is_final)

        if is_final:
            if session_id not in self._priority_queues:
                self._priority_queues[session_id] = deque()
            self._priority_queues[session_id].append(payload)
            logger.debug(
                "[QoS %s] Priority payload enqueued: session=%s",
                self._policy.adapter_key,
                session_id[:8],
            )
        else:
            if session_id in self._normal_slots:
                self._coalesced += 1
                age = time.monotonic() - self._normal_slots[session_id].enqueued_at
                logger.debug(
                    "[QoS %s] Coalesced superseded payload: session=%s age=%.2fs total_coalesced=%d",
                    self._policy.adapter_key,
                    session_id[:8],
                    age,
                    self._coalesced,
                )
            self._normal_slots[session_id] = payload

        # Maintain round-robin session order.
        if session_id not in self._rr_sessions:
            self._rr_sessions.append(session_id)

    # ------------------------------------------------------------------
    # Dispatch loop
    # ------------------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        """Background dispatch loop. Runs until cancelled."""
        while True:
            tick = self._compute_tick_s()
            await asyncio.sleep(tick)
            try:
                await self._dispatch_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "[QoS %s] Dispatch cycle error",
                    self._policy.adapter_key,
                    exc_info=True,
                )
            self._maybe_log_summary()

    async def _dispatch_cycle(self) -> None:
        """Execute one dispatch cycle.

        strict mode: dispatch ONE session payload (round-robin, priority first).
        coalesce_only mode: dispatch ALL pending session payloads.
        """
        raw_count = self._compute_active_count()
        self._update_ema(raw_count)

        if self._policy.mode == "coalesce_only":
            await self._dispatch_all_pending()
        else:  # strict
            await self._dispatch_one()

    async def _dispatch_all_pending(self) -> None:
        """Dispatch one payload per active session (coalesce_only mode)."""
        # Collect session IDs that have pending payloads.
        pending_sessions = list(set(list(self._priority_queues.keys()) + list(self._normal_slots.keys())))
        for session_id in pending_sessions:
            payload = self._pick_payload_for(session_id)
            if payload:
                await self._execute(payload)

    async def _dispatch_one(self) -> None:
        """Dispatch the next single payload in round-robin + priority order."""
        # Priority queue: find any session with a priority payload first.
        for session_id, q in list(self._priority_queues.items()):
            if q:
                payload = q.popleft()
                if not q:
                    del self._priority_queues[session_id]
                await self._execute(payload)
                return

        # Normal round-robin.
        if not self._normal_slots:
            return

        # Advance round-robin pointer to find a session with a pending slot.
        sessions_with_slots = [s for s in self._rr_sessions if s in self._normal_slots]
        if not sessions_with_slots:
            return

        # Keep rr_idx within bounds.
        self._rr_idx = self._rr_idx % len(sessions_with_slots)
        session_id = sessions_with_slots[self._rr_idx]
        self._rr_idx = (self._rr_idx + 1) % len(sessions_with_slots)

        payload = self._normal_slots.pop(session_id, None)
        if payload:
            await self._execute(payload)

    def _pick_payload_for(self, session_id: str) -> QoSPayload | None:
        """Pick the next payload for a specific session (priority first)."""
        q = self._priority_queues.get(session_id)
        if q:
            payload = q.popleft()
            if not q:
                del self._priority_queues[session_id]
            return payload
        return self._normal_slots.pop(session_id, None)

    async def _execute(self, payload: QoSPayload) -> None:
        """Execute a payload and update tracking state."""
        wait_age = time.monotonic() - payload.enqueued_at
        logger.debug(
            "[QoS %s] Dispatching: session=%s is_final=%s wait_age=%.2fs",
            self._policy.adapter_key,
            payload.session_id[:8],
            payload.is_final,
            wait_age,
        )
        try:
            await payload.factory()
            now = time.monotonic()
            self._active_emitters[payload.session_id] = now
            self._dispatched += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self._dispatch_errors += 1
            logger.error(
                "[QoS %s] Dispatch error: session=%s",
                self._policy.adapter_key,
                payload.session_id[:8],
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Cadence computation
    # ------------------------------------------------------------------

    def _compute_tick_s(self) -> float:
        """Compute the dispatch tick interval in seconds.

        coalesce_only: fixed at rounding_ms (no hard pacing).
        strict: computed from group budget and active emitter EMA.
        """
        if self._policy.mode == "coalesce_only":
            return self._policy.rounding_ms / 1000.0

        # Strict mode: derive tick from budget and active session count.
        effective_mpm = max(
            1,
            min(
                self._policy.group_mpm - self._policy.reserve_mpm,
                math.floor(self._policy.group_mpm * self._policy.output_budget_ratio),
            ),
        )
        global_tick_s = _ceil_to_ms(60.0 / effective_mpm, self._policy.rounding_ms)
        return global_tick_s

    def _compute_active_count(self) -> float:
        """Count currently active emitting sessions.

        Counts sessions with pending payloads plus sessions that dispatched within
        the active_emitter_window_s window.
        """
        now = time.monotonic()
        window = self._policy.active_emitter_window_s
        recently_active = {s for s, t in self._active_emitters.items() if now - t <= window}
        pending_sessions = set(self._normal_slots.keys()) | set(self._priority_queues.keys())
        return float(len(recently_active | pending_sessions))

    def _update_ema(self, raw_count: float) -> None:
        """Update the EMA-smoothed active session count."""
        alpha = self._policy.active_emitter_ema_alpha
        if self._ema_session_count == 0.0:
            self._ema_session_count = raw_count
        else:
            self._ema_session_count = alpha * raw_count + (1 - alpha) * self._ema_session_count

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def _maybe_log_summary(self) -> None:
        """Periodically log a cadence summary for operator observability."""
        now = time.monotonic()
        if now - self._last_summary_at < _SUMMARY_INTERVAL_S:
            return
        self._last_summary_at = now

        tick = self._compute_tick_s()
        queue_depth = len(self._normal_slots) + sum(len(q) for q in self._priority_queues.values())
        logger.info(
            "[QoS %s] Output cadence summary: mode=%s tick_s=%.2f active_sessions_ema=%.1f "
            "queue_depth=%d dispatched=%d coalesced=%d errors=%d",
            self._policy.adapter_key,
            self._policy.mode,
            tick,
            self._ema_session_count,
            queue_depth,
            self._dispatched,
            self._coalesced,
            self._dispatch_errors,
        )
