"""Daemon admission and settlement owner for graceful shutdown.

One module owns whether the daemon accepts new business work, which finite
accepted work is still in flight, and when that work has settled. Ingress
points consult the admission query before durable acceptance; accepted work
registers an owned unit that stays held until its effects and durable outcome
settle. The drain waits for the held units rather than cancelling them.

Phases only move forward: open, preparing, drained, stopping.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import time
from collections import Counter
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

CONTINUATION_HEADER = "X-TeleClaude-Continuation"
PREPARATION_PROTOCOL_VERSION = 1
PROCESS_INSTANCE_TOKEN = secrets.token_urlsafe(16)
PREPARATION_OBSERVATION_BUDGET_SECONDS = 90.0
REFUSAL_RETRY_AFTER_SECONDS = 5
_SETTLE_TASK = "shutdown-drain-settle"


class DrainPhase(StrEnum):
    """Monotone shutdown phases."""

    OPEN = "open"
    PREPARING = "preparing"
    DRAINED = "drained"
    STOPPING = "stopping"


_PHASE_ORDER: tuple[DrainPhase, ...] = (
    DrainPhase.OPEN,
    DrainPhase.PREPARING,
    DrainPhase.DRAINED,
    DrainPhase.STOPPING,
)


class ShutdownRefusal(Exception):
    """New business work refused because the daemon is draining.

    The refusal is retryable: nothing was accepted, recorded or claimed.
    """

    def __init__(self, work: str, phase: DrainPhase) -> None:
        super().__init__(f"daemon is shutting down ({phase}); refused new work: {work}")
        self.work = work
        self.phase = phase
        self.retry_after_seconds = REFUSAL_RETRY_AFTER_SECONDS


@dataclass(eq=False)
class OwnedUnit:
    """One finite accepted unit of work, held until its durable outcome settles."""

    label: str
    drain: ShutdownDrain = field(repr=False)
    continuation: str | None = field(default=None, repr=False)
    released: bool = field(default=False, repr=False)

    @property
    def held(self) -> bool:
        return not self.released

    @contextmanager
    def bound(self) -> Iterator[None]:
        """Make this unit the context's held owner for the duration of the block."""
        token = _held_unit.set(self)
        try:
            yield
        finally:
            _held_unit.reset(token)

    async def carry(self, work: Coroutine[object, object, T]) -> T:
        """Run the accepted work holding this unit, releasing it once the work has settled.

        Spawn the task that performs accepted work with `unit.carry(coro)`: the
        task holds the unit for its whole run, so everything it calls is
        admitted and the drain waits for it.
        """
        try:
            with self.bound():
                return await work
        finally:
            self.release()

    def release(self) -> None:
        """Settle the unit. Idempotent."""
        if self.released:
            return
        self.released = True
        self.continuation = None
        self.drain.unit_released(self)


_held_unit: ContextVar[OwnedUnit | None] = ContextVar("teleclaude_held_unit", default=None)


def held_unit() -> OwnedUnit | None:
    """The live owned unit the current context holds, if any."""
    unit = _held_unit.get()
    if unit is not None and unit.held:
        return unit
    return None


@dataclass(frozen=True)
class DrainObservation:
    """What a host caller may know about preparation: support, this process instance, and its phase."""

    protocol: int
    pid: int
    token: str
    phase: DrainPhase
    held_units: int
    budget_seconds: float


class ShutdownDrain:
    """Admission gate and settlement tracker. Loop-thread affine."""

    def __init__(self, budget_seconds: float = PREPARATION_OBSERVATION_BUDGET_SECONDS) -> None:
        self._phase = DrainPhase.OPEN
        self._units: set[OwnedUnit] = set()
        self._budget_seconds = budget_seconds
        self._deadline: float | None = None
        self._refusals: Counter[str] = Counter()
        self._settle_task: asyncio.Task[None] | None = None
        self._settled: asyncio.Event | None = None

    @property
    def phase(self) -> DrainPhase:
        return self._phase

    @property
    def is_open(self) -> bool:
        return self._phase is DrainPhase.OPEN

    def observation(self) -> DrainObservation:
        """The preparation capability, process instance identity and current phase."""
        return DrainObservation(
            protocol=PREPARATION_PROTOCOL_VERSION,
            pid=os.getpid(),
            token=PROCESS_INSTANCE_TOKEN,
            phase=self._phase,
            held_units=len(self._units),
            budget_seconds=self._budget_seconds,
        )

    def _advance(self, target: DrainPhase) -> None:
        if _PHASE_ORDER.index(target) <= _PHASE_ORDER.index(self._phase):
            return
        logger.info("Shutdown drain phase", previous=self._phase, phase=target, held_units=len(self._units))
        self._phase = target

    def check_admission(self, work: str) -> None:
        """Raise `ShutdownRefusal` unless the daemon is open or the caller holds an owner."""
        if self._phase is DrainPhase.OPEN or held_unit() is not None:
            return
        if self._refusals[work] == 0:
            logger.info("Refusing new work while draining", work=work, phase=self._phase)
        self._refusals[work] += 1
        raise ShutdownRefusal(work, self._phase)

    def begin_work(self, label: str) -> OwnedUnit:
        """Admit new finite work and register its owned unit before acceptance returns."""
        self.check_admission(label)
        return self.register(label)

    def register(self, label: str) -> OwnedUnit:
        """Register a unit for work whose admission was already decided."""
        unit = OwnedUnit(label=label, drain=self)
        self._units.add(unit)
        return unit

    def unit_released(self, unit: OwnedUnit) -> None:
        """Drop a released unit and wake the settlement waiter when none remain."""
        self._units.discard(unit)
        if not self._units and self._settled is not None:
            self._settled.set()

    def issue_continuation(self) -> str | None:
        """Mint (or reuse) the capability that lets a self-call continue the held unit's work."""
        unit = held_unit()
        if unit is None:
            return None
        if unit.continuation is None:
            unit.continuation = secrets.token_urlsafe(32)
        return unit.continuation

    def resolve_continuation(self, capability: str) -> OwnedUnit | None:
        """Resolve a capability to the unit that is still held, comparing in constant time."""
        presented = capability.encode()
        match: OwnedUnit | None = None
        for unit in self._units:
            issued = unit.continuation
            if issued is not None and hmac.compare_digest(presented, issued.encode()):
                match = unit
        return match

    def begin_preparation(self, reason: str) -> None:
        """Close admission to new business work. Idempotent and never reopens."""
        if self._phase is DrainPhase.OPEN:
            self._deadline = time.monotonic() + self._budget_seconds
            logger.info("Preparation for shutdown started", reason=reason, held_units=len(self._units))
            self._advance(DrainPhase.PREPARING)

    def remaining_budget(self) -> float:
        """Seconds left in the one preparation observation window."""
        if self._deadline is None:
            return self._budget_seconds
        return max(0.0, self._deadline - time.monotonic())

    def start_settling(self) -> asyncio.Task[None]:
        """Begin waiting for held units to settle. Idempotent; requires preparation."""
        if self._phase is DrainPhase.OPEN:
            raise RuntimeError("start_settling() requires preparation to have begun")
        if self._settle_task is None:
            self._settle_task = asyncio.get_running_loop().create_task(self._settle(), name=_SETTLE_TASK)
        return self._settle_task

    async def wait_settled(self) -> bool:
        """Wait for settlement within the preparation window; report whether it settled.

        An overrun cancels nothing: the settlement keeps waiting for the held
        units and the phase stays at preparing until they release.
        """
        settle_task = self.start_settling()
        try:
            await asyncio.wait_for(asyncio.shield(settle_task), timeout=self.remaining_budget())
        except TimeoutError:
            return False
        return True

    async def _settle(self) -> None:
        settled = asyncio.Event()
        self._settled = settled
        if not self._units:
            settled.set()
        try:
            await asyncio.wait_for(settled.wait(), timeout=self.remaining_budget())
        except TimeoutError:
            logger.warning(
                "Preparation window elapsed with unfinished accepted work",
                held=sorted(unit.label for unit in self._units),
                refusals=dict(self._refusals),
            )
            await settled.wait()
        self._advance(DrainPhase.DRAINED)
        logger.info("Accepted work settled", refusals=dict(self._refusals))

    def begin_stopping(self) -> None:
        """Mark teardown underway; admission stays closed."""
        self.begin_preparation("stopping")
        self._advance(DrainPhase.STOPPING)


_drain = ShutdownDrain()


def get_shutdown_drain() -> ShutdownDrain:
    """The process-wide drain owner."""
    return _drain
