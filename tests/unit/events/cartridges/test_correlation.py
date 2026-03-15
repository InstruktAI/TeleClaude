"""Characterization tests for teleclaude.events.cartridges.correlation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridges.correlation import CorrelationCartridge, CorrelationConfig
from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(
    event_type: str = "test.event",
    source: str = "test",
    entity: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source=source,
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        entity=entity,
    )


def _make_context(
    burst_count: int = 0,
    crash_count: int = 0,
    entity_fail_count: int = 0,
    producer: MagicMock | None = None,
    clock: datetime | None = None,
) -> MagicMock:
    fixed_clock = clock or datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    config = CorrelationConfig(
        window_seconds=300,
        burst_threshold=10,
        crash_cascade_threshold=3,
        entity_failure_threshold=3,
        clock=lambda: fixed_clock,
    )
    db = MagicMock()
    db.prune_correlation_windows = AsyncMock()
    db.increment_correlation_window = AsyncMock()
    db.get_correlation_count = AsyncMock(side_effect=[burst_count, crash_count, entity_fail_count])
    catalog = MagicMock(spec=EventCatalog)
    catalog.get.return_value = None
    ctx = MagicMock()
    ctx.correlation_config = config
    ctx.db = db
    ctx.catalog = catalog
    ctx.producer = producer
    return ctx


@pytest.mark.asyncio
async def test_synthetic_event_passes_through_unchanged():
    """Events from source 'correlation' bypass all pattern detection."""
    cartridge = CorrelationCartridge()
    event = _make_event(source="correlation")
    ctx = _make_context()

    result = await cartridge.process(event, ctx)

    assert result is event
    ctx.db.prune_correlation_windows.assert_not_called()
    ctx.db.increment_correlation_window.assert_not_called()


@pytest.mark.asyncio
async def test_below_burst_threshold_no_synthetic_emitted():
    """No burst event emitted when count is below threshold."""
    producer = MagicMock()
    producer.emit = AsyncMock()
    cartridge = CorrelationCartridge()
    event = _make_event()
    ctx = _make_context(burst_count=5, producer=producer)

    result = await cartridge.process(event, ctx)

    assert result is event
    producer.emit.assert_not_called()


@pytest.mark.asyncio
async def test_at_burst_threshold_emits_burst_detected():
    """Burst event is emitted when count reaches threshold."""
    producer = MagicMock()
    producer.emit = AsyncMock()
    cartridge = CorrelationCartridge()
    event = _make_event("test.event")
    ctx = _make_context(burst_count=10, producer=producer)

    result = await cartridge.process(event, ctx)

    assert result is event
    producer.emit.assert_called_once()
    emitted: EventEnvelope = producer.emit.call_args[0][0]
    assert emitted.event == "system.burst.detected"
    assert emitted.source == "correlation"


@pytest.mark.asyncio
async def test_burst_emitted_only_once_per_window_bucket():
    """Burst synthetic event is emitted only once per window bucket."""
    producer = MagicMock()
    producer.emit = AsyncMock()
    cartridge = CorrelationCartridge()
    event = _make_event("test.event")

    # First call: burst count at threshold, should emit
    ctx1 = _make_context(burst_count=10, producer=producer)
    await cartridge.process(event, ctx1)

    # Second call: same window bucket, same event type, should not emit again
    ctx2 = _make_context(burst_count=10, producer=producer)
    await cartridge.process(event, ctx2)

    assert producer.emit.call_count == 1


@pytest.mark.asyncio
async def test_crash_cascade_detected():
    """Crash cascade synthetic event emitted when worker crashes exceed threshold."""
    producer = MagicMock()
    producer.emit = AsyncMock()
    cartridge = CorrelationCartridge()
    event = _make_event("system.worker.crashed", entity="worker-1")
    ctx = _make_context(burst_count=0, crash_count=3, producer=producer)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert producer.emit.call_count >= 1
    cascade_calls = [c for c in producer.emit.call_args_list if c[0][0].event == "system.failure_cascade.detected"]
    assert len(cascade_calls) == 1


@pytest.mark.asyncio
async def test_entity_degraded_detected_for_failure_event():
    """Entity degraded event emitted when entity failure count reaches threshold."""
    producer = MagicMock()
    producer.emit = AsyncMock()
    cartridge = CorrelationCartridge()
    # Event type contains 'error' — matches _is_failure_type; entity set so entity path runs
    # get_correlation_count called twice: burst (call 1), entity_fail (call 2)
    # crash cascade path not taken since event != "system.worker.crashed"
    event = _make_event("service.error", entity="svc-1")
    fixed_clock = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    config = CorrelationConfig(
        window_seconds=300,
        burst_threshold=10,
        crash_cascade_threshold=3,
        entity_failure_threshold=3,
        clock=lambda: fixed_clock,
    )
    db = MagicMock()
    db.prune_correlation_windows = AsyncMock()
    db.increment_correlation_window = AsyncMock()
    # burst_count=0, then entity_fail_count=3
    db.get_correlation_count = AsyncMock(side_effect=[0, 3])
    catalog = MagicMock(spec=EventCatalog)
    catalog.get.return_value = None
    ctx = MagicMock()
    ctx.correlation_config = config
    ctx.db = db
    ctx.catalog = catalog
    ctx.producer = producer

    result = await cartridge.process(event, ctx)

    assert result is event
    degraded_calls = [c for c in producer.emit.call_args_list if c[0][0].event == "system.entity.degraded"]
    assert len(degraded_calls) == 1
    emitted: EventEnvelope = degraded_calls[0][0][0]
    assert emitted.payload["entity"] == "svc-1"


@pytest.mark.asyncio
async def test_no_producer_skips_synthetic_emit():
    """When context.producer is None, no burst event is emitted (no crash)."""
    cartridge = CorrelationCartridge()
    event = _make_event("test.event")
    ctx = _make_context(burst_count=10, producer=None)

    # Should not raise
    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_non_failure_event_does_not_trigger_entity_degraded():
    """Events without failure keywords do not trigger entity degradation detection."""
    producer = MagicMock()
    producer.emit = AsyncMock()
    cartridge = CorrelationCartridge()
    event = _make_event("service.started", entity="svc-1")
    ctx = _make_context(burst_count=0, crash_count=0, entity_fail_count=5, producer=producer)

    await cartridge.process(event, ctx)

    degraded_calls = [c for c in producer.emit.call_args_list if c[0][0].event == "system.entity.degraded"]
    assert len(degraded_calls) == 0
