"""Tests for the correlation cartridge."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude_events.cartridges.correlation import CorrelationCartridge, CorrelationConfig
from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext


def _fixed_clock(dt: datetime):
    return lambda: dt


def _make_context(
    db: EventDB,
    producer: object = None,
    config: CorrelationConfig | None = None,
) -> PipelineContext:
    ctx = PipelineContext(
        catalog=EventCatalog(),
        db=db,
        correlation_config=config or CorrelationConfig(),
        producer=producer,
    )
    return ctx


def _make_event(
    event: str = "test.happened",
    source: str = "daemon",
    entity: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(event=event, source=source, level=EventLevel.WORKFLOW, entity=entity)


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_correlation.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
async def test_passes_all_events_through(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = CorrelationCartridge()

    event = _make_event()
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.event == "test.happened"


@pytest.mark.asyncio
async def test_burst_detected_emits_synthetic(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(window_seconds=300, burst_threshold=3, clock=_fixed_clock(now))
    mock_producer = AsyncMock()
    ctx = _make_context(db, producer=mock_producer, config=config)
    cartridge = CorrelationCartridge()

    # Pre-seed 2 events in the window so that the 3rd triggers the burst
    await db.increment_correlation_window("test.happened", None, now - timedelta(seconds=10))
    await db.increment_correlation_window("test.happened", None, now - timedelta(seconds=5))

    event = _make_event(event="test.happened")
    result = await cartridge.process(event, ctx)

    assert result is not None
    mock_producer.emit.assert_awaited_once()
    emitted = mock_producer.emit.call_args[0][0]
    assert emitted.event == "system.burst.detected"
    assert emitted.source == "correlation"
    assert emitted.payload["event_type"] == "test.happened"


@pytest.mark.asyncio
async def test_burst_not_repeated_within_same_window(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(window_seconds=300, burst_threshold=3, clock=_fixed_clock(now))
    mock_producer = AsyncMock()
    ctx = _make_context(db, producer=mock_producer, config=config)
    cartridge = CorrelationCartridge()

    # Pre-seed 2 events so threshold is hit on first process call
    await db.increment_correlation_window("test.happened", None, now - timedelta(seconds=10))
    await db.increment_correlation_window("test.happened", None, now - timedelta(seconds=5))

    # First event crosses threshold → emit
    await cartridge.process(_make_event(event="test.happened"), ctx)
    assert mock_producer.emit.call_count == 1

    # Second event — still above threshold in the same window bucket → must NOT re-emit
    await cartridge.process(_make_event(event="test.happened"), ctx)
    assert mock_producer.emit.call_count == 1


@pytest.mark.asyncio
async def test_burst_below_threshold_no_emit(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(window_seconds=300, burst_threshold=5, clock=_fixed_clock(now))
    mock_producer = AsyncMock()
    ctx = _make_context(db, producer=mock_producer, config=config)
    cartridge = CorrelationCartridge()

    # 3 events, threshold is 5 → no burst
    for i in range(3):
        await db.increment_correlation_window("test.happened", None, now - timedelta(seconds=i + 1))

    event = _make_event(event="test.happened")
    await cartridge.process(event, ctx)  # 4th event, still below 5

    mock_producer.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_correlation_source_skipped(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(clock=_fixed_clock(now))
    mock_producer = AsyncMock()
    ctx = _make_context(db, producer=mock_producer, config=config)
    cartridge = CorrelationCartridge()

    # Event from correlation source should be skipped
    event = _make_event(source="correlation")
    result = await cartridge.process(event, ctx)

    assert result is not None
    # No DB row should have been added
    count = await db.get_correlation_count("test.happened", None, now - timedelta(seconds=300))
    assert count == 0
    mock_producer.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cascade_detected(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(
        window_seconds=300, crash_cascade_threshold=3, burst_threshold=100, clock=_fixed_clock(now)
    )
    mock_producer = AsyncMock()
    ctx = _make_context(db, producer=mock_producer, config=config)
    cartridge = CorrelationCartridge()

    # Seed 2 crash events in window
    await db.increment_correlation_window("system.worker.crashed", "worker-1", now - timedelta(seconds=10))
    await db.increment_correlation_window("system.worker.crashed", "worker-2", now - timedelta(seconds=5))

    # 3rd crash triggers cascade
    event = _make_event(event="system.worker.crashed", entity="worker-3")
    await cartridge.process(event, ctx)

    emitted_events = [call[0][0].event for call in mock_producer.emit.call_args_list]
    assert "system.failure_cascade.detected" in emitted_events


@pytest.mark.asyncio
async def test_entity_degraded(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(
        window_seconds=300,
        entity_failure_threshold=3,
        burst_threshold=100,
        crash_cascade_threshold=100,
        clock=_fixed_clock(now),
    )
    mock_producer = AsyncMock()
    ctx = _make_context(db, producer=mock_producer, config=config)
    cartridge = CorrelationCartridge()

    entity = "telec://worker/my-worker"
    # Seed 2 crash events for same entity
    await db.increment_correlation_window("system.worker.crashed", entity, now - timedelta(seconds=10))
    await db.increment_correlation_window("system.worker.crashed", entity, now - timedelta(seconds=5))

    # 3rd crash for same entity triggers entity degraded
    event = _make_event(event="system.worker.crashed", entity=entity)
    await cartridge.process(event, ctx)

    emitted_events = [call[0][0].event for call in mock_producer.emit.call_args_list]
    assert "system.entity.degraded" in emitted_events


@pytest.mark.asyncio
async def test_stale_window_pruned(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(window_seconds=300, burst_threshold=100, clock=_fixed_clock(now))
    ctx = _make_context(db, config=config)
    cartridge = CorrelationCartridge()

    # Insert an old row (older than 2x window = 600s)
    old_ts = now - timedelta(seconds=700)
    await db.increment_correlation_window("old.event", None, old_ts)

    # Process a new event — pruning happens inside
    event = _make_event()
    await cartridge.process(event, ctx)

    # Old row should be pruned
    count = await db.get_correlation_count("old.event", None, old_ts)
    assert count == 0


@pytest.mark.asyncio
async def test_no_producer_logs_warning(db: EventDB) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)
    config = CorrelationConfig(window_seconds=300, burst_threshold=1, clock=_fixed_clock(now))
    ctx = _make_context(db, producer=None, config=config)  # No producer
    cartridge = CorrelationCartridge()

    with patch("teleclaude_events.cartridges.correlation.logger") as mock_logger:
        # First event triggers burst (threshold=1)
        event = _make_event()
        result = await cartridge.process(event, ctx)

    assert result is not None  # Event passes through
    mock_logger.warning.assert_called()
    warning_msg = mock_logger.warning.call_args[0][0]
    assert "no producer" in warning_msg
