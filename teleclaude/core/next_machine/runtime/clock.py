"""Lifecycle scheduler clock for task schedules."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.shutdown_drain import get_shutdown_drain
from teleclaude.events import EventLevel, EventProducer, EventVisibility
from teleclaude.events.envelope import EventHomeMarker, occurrence_id
from teleclaude.events.references import ComputerRef
from teleclaude.events.schemas.sdlc import SchedulerTickData, SchedulerTickMinute
from teleclaude.events.wire import LegacyFacts

logger = get_logger(__name__)

_SCHEDULER_TICK_KEY = "scheduler.tick.minute"


def next_minute_delay(now: datetime | None = None) -> float:
    """Seconds until the next wall-clock minute boundary."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    next_minute = (current + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return max(0.0, (next_minute - current).total_seconds())


class TaskScheduleClock:
    """Emit a stateless minute wake-up for the lifecycle router."""

    def __init__(self, producer: EventProducer) -> None:
        self._producer = producer

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Run until shutdown, re-anchoring each wait to the next minute."""
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=next_minute_delay())
                break
            except TimeoutError:
                pass
            if not get_shutdown_drain().is_open:
                # A tick refused downstream would burn the event processor's retries; emit none while draining.
                continue
            ticked_at = datetime.now(UTC).replace(second=0, microsecond=0)
            tick_key = f"{_SCHEDULER_TICK_KEY}:{config.computer.name}:{ticked_at.isoformat()}"
            await self._producer.emit(
                SchedulerTickMinute(
                    id=occurrence_id(tick_key),
                    subject=ComputerRef(config.computer.name),
                    home=EventHomeMarker.NONE,
                    data=SchedulerTickData(computer=config.computer.name, ticked_at=ticked_at.isoformat()),
                ),
                LegacyFacts(
                    producer="daemon",
                    level=EventLevel.WORKFLOW,
                    domain="sdlc",
                    visibility=EventVisibility.CLUSTER,
                    description="Lifecycle scheduler minute tick",
                    idempotency_key=tick_key,
                ),
            )
            logger.debug("scheduler minute tick emitted", ticked_at=ticked_at.isoformat())
