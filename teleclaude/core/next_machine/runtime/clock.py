"""Lifecycle scheduler clock for task schedules."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.events import EventLevel, EventProducer, EventVisibility
from teleclaude.events.envelope import EventEnvelope

logger = get_logger(__name__)

SCHEDULER_TICK_MINUTE = "scheduler.tick.minute"


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
            ticked_at = datetime.now(UTC).replace(second=0, microsecond=0)
            await self._producer.emit(
                EventEnvelope(
                    event=SCHEDULER_TICK_MINUTE,
                    source="daemon",
                    level=EventLevel.WORKFLOW,
                    domain="software-development",
                    visibility=EventVisibility.CLUSTER,
                    description="Lifecycle scheduler minute tick",
                    payload={
                        "computer": config.computer.name,
                        "ticked_at": ticked_at.isoformat(),
                    },
                    idempotency_key=f"{SCHEDULER_TICK_MINUTE}:{config.computer.name}:{ticked_at.isoformat()}",
                )
            )
            logger.debug("scheduler minute tick emitted", ticked_at=ticked_at.isoformat())
