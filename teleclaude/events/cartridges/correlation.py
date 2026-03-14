"""Correlation cartridge — detects burst, cascade, and entity degradation patterns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)

_FAILURE_TYPE_KEYWORDS = ("crash", "fail", "error")


def _is_failure_type(event_type: str) -> bool:
    return any(kw in event_type.lower() for kw in _FAILURE_TYPE_KEYWORDS)


@dataclass
class CorrelationConfig:
    window_seconds: int = 300
    burst_threshold: int = 10
    crash_cascade_threshold: int = 3
    entity_failure_threshold: int = 3
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


class CorrelationCartridge:
    name = "correlation"

    def __init__(self) -> None:
        self._emitted_bursts: set[tuple[str, int]] = set()

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        # Skip synthetic events from correlation to prevent re-entry loops
        if event.source == "correlation":
            return event

        config = context.correlation_config
        now = config.clock()
        window_start = now - timedelta(seconds=config.window_seconds)
        prune_before = now - timedelta(seconds=2 * config.window_seconds)

        await context.db.prune_correlation_windows(older_than=prune_before)
        await context.db.increment_correlation_window(event.event, event.entity, now)

        # Burst detection: N events of same type in window — emit once per window bucket
        burst_count = await context.db.get_correlation_count(event.event, None, window_start)
        if burst_count >= config.burst_threshold:
            window_bucket = int(now.timestamp() // config.window_seconds)
            burst_key = (event.event, window_bucket)
            if burst_key not in self._emitted_bursts:
                self._emitted_bursts.add(burst_key)
                await self._emit_synthetic(
                    "system.burst.detected",
                    {
                        "event_type": event.event,
                        "window_start": window_start.isoformat(),
                        "count": burst_count,
                    },
                    context,
                )

        # Crash cascade detection
        if event.event == "system.worker.crashed":
            crash_count = await context.db.get_correlation_count("system.worker.crashed", None, window_start)
            if crash_count >= config.crash_cascade_threshold:
                workers = [event.entity] if event.entity else []
                await self._emit_synthetic(
                    "system.failure_cascade.detected",
                    {
                        "crash_count": crash_count,
                        "window_start": window_start.isoformat(),
                        "workers": workers,  # type: ignore[dict-item]
                    },
                    context,
                )

        # Entity failure detection
        if event.entity is not None and _is_failure_type(event.event):
            entity_fail_count = await context.db.get_correlation_count(event.event, event.entity, window_start)
            if entity_fail_count >= config.entity_failure_threshold:
                await self._emit_synthetic(
                    "system.entity.degraded",
                    {
                        "entity": event.entity,
                        "failure_count": entity_fail_count,
                        "window_start": window_start.isoformat(),
                    },
                    context,
                )

        return event

    async def _emit_synthetic(self, event_type: str, payload: JsonDict, context: PipelineContext) -> None:
        if context.producer is None:
            logger.warning(
                "correlation: no producer configured, cannot emit synthetic event",
                event_type=event_type,
            )
            return

        schema = context.catalog.get(event_type)
        level = schema.default_level if schema else EventLevel.OPERATIONAL
        visibility = schema.default_visibility if schema else EventVisibility.LOCAL

        envelope = EventEnvelope(
            event=event_type,
            source="correlation",
            level=level,
            domain="system",
            visibility=visibility,
            payload=payload,
        )
        await context.producer.emit(envelope)
