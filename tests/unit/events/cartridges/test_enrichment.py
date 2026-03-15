"""Characterization tests for teleclaude.events.cartridges.enrichment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from teleclaude.events.cartridges.enrichment import EnrichmentCartridge
from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(entity: str | None = None) -> EventEnvelope:
    return EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        entity=entity,
    )


def _make_context(db: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.db = db
    return ctx


@pytest.mark.asyncio
async def test_no_entity_passes_through():
    """Events with no entity are passed through unchanged."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity=None)
    ctx = _make_context(MagicMock())

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_non_telec_uri_passes_through():
    """Entity URI not starting with telec:// is not enriched."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="other://something")
    db = MagicMock(spec=EventDB)
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_telec_uri_without_slash_passes_through():
    """telec:// URI without type/id separator passes through unchanged."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://noslash")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=0)
    db.get_latest_event_payload = AsyncMock(return_value=None)
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_todo_entity_no_data_passes_through():
    """todo entity with no failure/DOR/phase data returns event unchanged."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://todo/my-slug")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=0)
    db.get_latest_event_payload = AsyncMock(return_value=None)
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_todo_entity_with_failure_data_enriches():
    """todo entity with failure history gets enrichment annotation."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://todo/my-slug")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=2)
    db.get_latest_event_payload = AsyncMock(return_value=None)
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is not None
    enrichment = result.payload["_enrichment"]
    assert enrichment["failure_count"] == 2
    assert enrichment["last_dor_score"] is None
    assert enrichment["current_phase"] is None


@pytest.mark.asyncio
async def test_todo_entity_with_dor_score_enriches():
    """todo entity with DOR score gets last_dor_score in enrichment."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://todo/my-slug")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=0)
    db.get_latest_event_payload = AsyncMock(side_effect=[{"score": 8}, None])
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.payload["_enrichment"]["last_dor_score"] == 8


@pytest.mark.asyncio
async def test_worker_entity_no_crashes_passes_through():
    """worker entity with no recent crashes is not enriched."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://worker/worker-1")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=0)
    db.get_latest_event_payload = AsyncMock(return_value=None)
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_worker_entity_with_crashes_enriches():
    """worker entity with crash history gets enrichment annotation."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://worker/worker-1")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=3)
    db.get_latest_event_payload = AsyncMock(return_value={"timestamp": "2025-01-01T00:00:00"})
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is not None
    enrichment = result.payload["_enrichment"]
    assert enrichment["crash_count"] == 3
    assert enrichment["last_crash_at"] == "2025-01-01T00:00:00"


@pytest.mark.asyncio
async def test_unknown_entity_type_passes_through():
    """Unrecognized telec:// entity type (not todo or worker) passes through."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://session/abc-123")
    db = MagicMock(spec=EventDB)
    ctx = _make_context(db)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_todo_enrichment_queries_correct_event_and_filter():
    """_enrich_todo queries build.completed with success=False filter for the entity URI."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://todo/my-slug")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=0)
    db.get_latest_event_payload = AsyncMock(return_value=None)
    ctx = _make_context(db)

    await cartridge.process(event, ctx)

    db.count_events_by_entity.assert_called_once_with(
        "telec://todo/my-slug",
        "domain.software-development.build.completed",
        payload_filter={"success": False},
    )
    assert db.get_latest_event_payload.call_args_list == [
        call("telec://todo/my-slug", "dor_assessed"),
        call("telec://todo/my-slug", "todo_activated"),
    ]


@pytest.mark.asyncio
async def test_worker_enrichment_queries_correct_event_and_since_kwarg():
    """_enrich_worker queries system.worker.crashed with a since= cutoff for the entity URI."""
    cartridge = EnrichmentCartridge()
    event = _make_event(entity="telec://worker/worker-1")
    db = MagicMock(spec=EventDB)
    db.count_events_by_entity = AsyncMock(return_value=0)
    db.get_latest_event_payload = AsyncMock(return_value=None)
    ctx = _make_context(db)
    lower_bound = datetime.now(UTC) - timedelta(hours=24, seconds=1)

    await cartridge.process(event, ctx)

    db.count_events_by_entity.assert_called_once()
    args = db.count_events_by_entity.call_args
    assert args[0][0] == "telec://worker/worker-1"
    assert args[0][1] == "system.worker.crashed"
    assert "since" in args[1]
    assert lower_bound <= args[1]["since"] <= datetime.now(UTC) - timedelta(hours=24) + timedelta(seconds=1)
    db.get_latest_event_payload.assert_called_once_with("telec://worker/worker-1", "system.worker.crashed")
