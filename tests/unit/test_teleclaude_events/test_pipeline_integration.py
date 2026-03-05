"""Integration tests for the full 6-cartridge pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from teleclaude_events.cartridges import (
    ClassificationCartridge,
    CorrelationCartridge,
    DeduplicationCartridge,
    EnrichmentCartridge,
    NotificationProjectorCartridge,
    TrustCartridge,
)
from teleclaude_events.cartridges.correlation import CorrelationConfig
from teleclaude_events.cartridges.trust import TrustConfig
from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import Pipeline, PipelineContext


def _build_catalog() -> EventCatalog:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.created",
            description="Test event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True),
        )
    )
    return catalog


def _make_event(
    event: str = "test.created",
    source: str = "daemon",
    slug: str = "my-task",
) -> EventEnvelope:
    return EventEnvelope(
        event=event,
        source=source,
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": slug},
    )


def _build_pipeline(
    db: EventDB,
    catalog: EventCatalog,
    producer: object = None,
    trust_config: TrustConfig | None = None,
    correlation_config: CorrelationConfig | None = None,
) -> tuple[Pipeline, PipelineContext]:
    ctx = PipelineContext(
        catalog=catalog,
        db=db,
        trust_config=trust_config or TrustConfig(known_sources=frozenset({"daemon", "correlation"})),
        correlation_config=correlation_config or CorrelationConfig(burst_threshold=100),
        producer=producer,
    )
    pipeline = Pipeline(
        [
            TrustCartridge(),
            DeduplicationCartridge(),
            EnrichmentCartridge(),
            CorrelationCartridge(),
            ClassificationCartridge(),
            NotificationProjectorCartridge(),
        ],
        ctx,
    )
    return pipeline, ctx


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_integration.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
async def test_pipeline_order_trust_drops_before_dedup(db: EventDB) -> None:
    """Event rejected by trust never increments dedup check."""
    catalog = _build_catalog()
    # Trust config with no known sources → any event gets flagged/quarantined in strict mode
    trust_config = TrustConfig(strictness="strict", known_sources=frozenset())
    pipeline, _ctx = _build_pipeline(db, catalog, trust_config=trust_config)

    event = _make_event(source="unknown-source")
    result = await pipeline.execute(event)

    # Trust quarantined/rejected the event
    assert result is None
    # Dedup was never reached → no idempotency key in DB
    key = catalog.build_idempotency_key("test.created", {"slug": "my-task"})
    assert key is not None
    exists = await db.idempotency_key_exists(key)
    assert not exists


@pytest.mark.asyncio
async def test_pipeline_order_dedup_drops_before_enrichment(db: EventDB) -> None:
    """Duplicate event never reaches enrichment."""
    catalog = _build_catalog()
    push_cb = AsyncMock()
    pipeline, ctx = _build_pipeline(db, catalog)
    ctx.push_callbacks.append(push_cb)

    # First pass — creates notification
    event1 = _make_event(slug="dup-task")
    result1 = await pipeline.execute(event1)
    assert result1 is not None
    push_cb.assert_awaited_once()
    push_cb.reset_mock()

    # Second pass — same slug, dedup should drop it
    event2 = _make_event(slug="dup-task")
    result2 = await pipeline.execute(event2)
    assert result2 is None
    push_cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_full_pass(db: EventDB) -> None:
    """Clean event flows through all 6 cartridges, ends with _classification in payload."""
    catalog = _build_catalog()
    push_cb = AsyncMock()
    pipeline, _ = _build_pipeline(db, catalog, producer=None)
    pipeline._context.push_callbacks.append(push_cb)

    event = _make_event(slug="fresh-task")
    result = await pipeline.execute(event)

    assert result is not None
    assert "_classification" in result.payload
    assert result.payload["_classification"]["treatment"] == "notification-worthy"
    push_cb.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_synthetic_event_reenters(db: EventDB) -> None:
    """Correlation emits synthetic event; mock producer captures it."""
    catalog = _build_catalog()
    # Set burst threshold to 1 so the first event triggers burst detection
    corr_config = CorrelationConfig(
        burst_threshold=1,
        clock=lambda: datetime(2024, 1, 1, 12, 0, 0),
    )
    mock_producer = AsyncMock()
    pipeline, _ = _build_pipeline(db, catalog, producer=mock_producer, correlation_config=corr_config)

    event = _make_event(slug="burst-task")
    result = await pipeline.execute(event)

    assert result is not None
    # Producer should have been called with the synthetic burst event
    mock_producer.emit.assert_awaited_once()
    emitted = mock_producer.emit.call_args[0][0]
    assert emitted.event == "system.burst.detected"
    assert emitted.source == "correlation"


@pytest.mark.asyncio
async def test_notification_projector_uses_classification(db: EventDB) -> None:
    """Projector fast-paths signal-only events without catalog lookup."""
    catalog = EventCatalog()  # Empty catalog — no schema registered
    _pipeline, ctx = _build_pipeline(db, catalog)

    # Event has _classification pre-set as signal-only (as if classification cartridge ran)
    event = EventEnvelope(
        event="unknown.event",
        source="daemon",
        level=EventLevel.WORKFLOW,
        payload={"_classification": {"treatment": "signal-only", "actionable": False}},
    )

    # Run only the notification projector (not the full pipeline)
    from teleclaude_events.cartridges.notification import NotificationProjectorCartridge

    projector = NotificationProjectorCartridge()
    result = await projector.process(event, ctx)

    assert result is not None
    # No notification should be created
    rows = await db.list_notifications()
    assert len(rows) == 0
