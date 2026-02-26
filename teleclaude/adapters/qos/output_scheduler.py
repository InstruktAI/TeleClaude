"""Generic adapter output scheduler with coalescing and fairness."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from instrukt_ai_logging import get_logger

from .policy import CadenceDecision, OutputPriority, OutputQoSMode, OutputQoSPolicy

logger = get_logger(__name__)

DispatchCallable = Callable[[], Awaitable[str | None]]


@dataclass(frozen=True)
class SchedulerSnapshot:
    """Operational scheduler counters for tests and diagnostics."""

    adapter_key: str
    mode: OutputQoSMode
    queue_depth: int
    active_sessions: int
    superseded_payloads: int
    retry_after_count: int
    cadence: CadenceDecision


@dataclass
class _QueuedPayload:
    priority: OutputPriority
    dispatch: DispatchCallable
    enqueued_at: float


@dataclass
class _SessionState:
    high: deque[_QueuedPayload] = field(default_factory=deque)
    normal: _QueuedPayload | None = None
    dispatching: bool = False
    last_emitted_at: float | None = None
    last_wait_age_s: float = 0.0

    def has_pending(self) -> bool:
        return bool(self.high) or self.normal is not None

    def queue_depth(self) -> int:
        return len(self.high) + (1 if self.normal is not None else 0)

    def pop_next(self) -> _QueuedPayload | None:
        if self.high:
            return self.high.popleft()
        if self.normal is not None:
            payload = self.normal
            self.normal = None
            return payload
        return None


class OutputScheduler:
    """Adapter-local output scheduler with latest-only coalescing."""

    def __init__(
        self,
        *,
        adapter_key: str,
        policy: OutputQoSPolicy,
        summary_interval_s: float = 5.0,
    ) -> None:
        self._adapter_key = adapter_key
        self._policy = policy
        self._summary_interval_s = summary_interval_s

        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None

        self._sessions: dict[str, _SessionState] = {}
        self._session_rr: deque[str] = deque()

        self._superseded_payloads = 0
        self._retry_after_count = 0
        self._smoothed_active_emitters = 1.0
        self._last_cadence = CadenceDecision(effective_output_mpm=0, global_tick_s=0.0, session_tick_s=0.0)
        self._last_summary_at = 0.0

    async def stop(self) -> None:
        """Stop background worker if active."""
        task = self._worker_task
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    def record_retry_after(self, _session_id: str) -> None:
        """Increment rate-limit incidence metric."""
        self._retry_after_count += 1

    def snapshot(self) -> SchedulerSnapshot:
        """Return current scheduler counters."""
        return SchedulerSnapshot(
            adapter_key=self._adapter_key,
            mode=self._policy.mode,
            queue_depth=sum(state.queue_depth() for state in self._sessions.values()),
            active_sessions=self._count_active_sessions(time.monotonic()),
            superseded_payloads=self._superseded_payloads,
            retry_after_count=self._retry_after_count,
            cadence=self._last_cadence,
        )

    async def submit(self, session_id: str, priority: OutputPriority, dispatch: DispatchCallable) -> str | None:
        """Submit payload and maybe dispatch immediately."""
        if self._policy.mode == OutputQoSMode.OFF:
            return await dispatch()

        now = time.monotonic()
        payload = _QueuedPayload(priority=priority, dispatch=dispatch, enqueued_at=now)

        inline_session: str | None = None
        inline_payload: _QueuedPayload | None = None

        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = _SessionState()
                self._sessions[session_id] = state
                self._session_rr.append(session_id)

            self._enqueue_locked(state, payload)

            if self._can_inline_dispatch_locked(session_id, now):
                next_payload = state.pop_next()
                if next_payload is not None:
                    state.dispatching = True
                    inline_session = session_id
                    inline_payload = next_payload
            else:
                self._ensure_worker_locked()
                self._wake.set()

        if inline_session is not None and inline_payload is not None:
            return await self._dispatch_payload(inline_session, inline_payload, propagate_exceptions=True)
        return None

    def _enqueue_locked(self, state: _SessionState, payload: _QueuedPayload) -> None:
        if payload.priority == OutputPriority.HIGH:
            state.high.append(payload)
            return

        if not self._policy.should_coalesce(OutputPriority.NORMAL):
            state.high.append(payload)
            return

        if state.normal is not None:
            self._superseded_payloads += 1
        state.normal = payload

    def _ensure_worker_locked(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker_loop(), name=f"qos-{self._adapter_key}")

    def _can_inline_dispatch_locked(self, session_id: str, now: float) -> bool:
        if self._policy.mode == OutputQoSMode.STRICT:
            if self._pending_sessions_locked() > 1:
                return False
            if self._any_dispatching_locked():
                return False

            ready_at = self._next_ready_at_locked(session_id, now)
            if ready_at > now:
                return False

        return True

    def _pending_sessions_locked(self) -> int:
        return sum(1 for state in self._sessions.values() if state.has_pending())

    def _any_dispatching_locked(self) -> bool:
        return any(state.dispatching for state in self._sessions.values())

    async def _worker_loop(self) -> None:
        while True:
            selected_session: str | None = None
            selected_payload: _QueuedPayload | None = None
            sleep_for_s: float | None = None

            async with self._lock:
                now = time.monotonic()
                selected_session, selected_payload, sleep_for_s = self._select_next_locked(now)
                if selected_session is None or selected_payload is None:
                    if self._pending_sessions_locked() == 0:
                        self._worker_task = None
                        return
                    self._wake.clear()
                else:
                    self._sessions[selected_session].dispatching = True

            if selected_session is not None and selected_payload is not None:
                await self._dispatch_payload(selected_session, selected_payload, propagate_exceptions=False)
                continue

            try:
                if sleep_for_s is None:
                    await self._wake.wait()
                else:
                    await asyncio.wait_for(self._wake.wait(), timeout=max(0.01, sleep_for_s))
            except asyncio.TimeoutError:
                continue

    def _select_next_locked(self, now: float) -> tuple[str | None, _QueuedPayload | None, float | None]:
        cadence = self._recompute_cadence_locked(now)

        if not self._session_rr:
            return None, None, None

        candidate_due: float | None = None
        selected_session: str | None = None
        selected_payload: _QueuedPayload | None = None

        for _ in range(len(self._session_rr)):
            session_id = self._session_rr[0]
            self._session_rr.rotate(-1)
            state = self._sessions.get(session_id)
            if state is None:
                continue
            if state.dispatching or not state.has_pending():
                continue

            ready_at = self._ready_at_for_state(state, cadence, now)
            if ready_at <= now:
                selected_session = session_id
                selected_payload = state.pop_next()
                break

            if candidate_due is None or ready_at < candidate_due:
                candidate_due = ready_at

        if selected_session is not None and selected_payload is not None:
            return selected_session, selected_payload, None

        if candidate_due is None:
            return None, None, None
        return None, None, max(0.0, candidate_due - now)

    async def _dispatch_payload(
        self,
        session_id: str,
        payload: _QueuedPayload,
        *,
        propagate_exceptions: bool,
    ) -> str | None:
        result: str | None = None
        dispatch_error: Exception | None = None
        try:
            result = await payload.dispatch()
        except Exception as exc:  # noqa: BLE001 - lane errors are logged and scheduler keeps running
            dispatch_error = exc
            logger.warning(
                "Output scheduler dispatch failed: adapter=%s session=%s error=%s",
                self._adapter_key,
                session_id[:8],
                exc,
            )
        finally:
            now = time.monotonic()
            async with self._lock:
                state = self._sessions.get(session_id)
                if state is not None:
                    state.dispatching = False
                    state.last_emitted_at = now
                    state.last_wait_age_s = max(0.0, now - payload.enqueued_at)
                self._recompute_cadence_locked(now)
                self._maybe_log_summary_locked(now)
                self._wake.set()

        if dispatch_error is not None and propagate_exceptions:
            raise dispatch_error
        return result

    def _ready_at_for_state(self, state: _SessionState, cadence: CadenceDecision, now: float) -> float:
        if self._policy.mode != OutputQoSMode.STRICT:
            return now
        if state.last_emitted_at is None:
            return now
        return state.last_emitted_at + cadence.session_tick_s

    def _next_ready_at_locked(self, session_id: str, now: float) -> float:
        state = self._sessions[session_id]
        cadence = self._recompute_cadence_locked(now)
        return self._ready_at_for_state(state, cadence, now)

    def _count_active_sessions(self, now: float) -> int:
        active: set[str] = set()
        for session_id, state in self._sessions.items():
            if state.has_pending() or state.dispatching:
                active.add(session_id)
                continue
            if state.last_emitted_at is None:
                continue
            if (now - state.last_emitted_at) <= self._policy.active_emitter_window_s:
                active.add(session_id)
        return max(1, len(active))

    def _recompute_cadence_locked(self, now: float) -> CadenceDecision:
        active_now = self._count_active_sessions(now)
        alpha = min(max(self._policy.active_emitter_ema_alpha, 0.0), 1.0)
        if alpha >= 1.0:
            smoothed = float(active_now)
        else:
            smoothed = (alpha * float(active_now)) + ((1.0 - alpha) * self._smoothed_active_emitters)
        self._smoothed_active_emitters = max(1.0, smoothed)
        self._last_cadence = self._policy.compute_cadence(
            active_emitting_sessions=active_now,
            smoothed_active_emitters=self._smoothed_active_emitters,
        )
        return self._last_cadence

    def _maybe_log_summary_locked(self, now: float) -> None:
        if (now - self._last_summary_at) < self._summary_interval_s:
            return
        self._last_summary_at = now
        snapshot = self.snapshot()
        logger.info(
            "Output cadence summary",
            adapter=snapshot.adapter_key,
            mode=snapshot.mode.value,
            queue_depth=snapshot.queue_depth,
            active_sessions=snapshot.active_sessions,
            superseded=snapshot.superseded_payloads,
            effective_output_mpm=snapshot.cadence.effective_output_mpm,
            global_tick_s=snapshot.cadence.global_tick_s,
            session_tick_s=snapshot.cadence.session_tick_s,
            retry_after=snapshot.retry_after_count,
        )
