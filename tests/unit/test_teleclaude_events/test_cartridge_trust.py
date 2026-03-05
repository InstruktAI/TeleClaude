"""Tests for the trust evaluator cartridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude_events.cartridges.trust import TrustCartridge, TrustConfig
from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext


def _make_context(db: EventDB, trust_config: TrustConfig | None = None) -> PipelineContext:
    return PipelineContext(
        catalog=EventCatalog(),
        db=db,
        trust_config=trust_config or TrustConfig(),
    )


def _make_event(source: str = "myapp", level: EventLevel = EventLevel.WORKFLOW, domain: str = "test") -> EventEnvelope:
    return EventEnvelope(event="test.event", source=source, level=level, domain=domain)


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_trust.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
async def test_known_source_accepted(db: EventDB) -> None:
    config = TrustConfig(strictness="standard", known_sources=frozenset({"myapp"}))
    ctx = _make_context(db, config)
    cartridge = TrustCartridge()

    event = _make_event(source="myapp")
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_trust_flags" not in result.payload


@pytest.mark.asyncio
async def test_unknown_source_standard_flagged(db: EventDB) -> None:
    config = TrustConfig(strictness="standard", known_sources=frozenset())
    ctx = _make_context(db, config)
    cartridge = TrustCartridge()

    event = _make_event(source="unknown-source")
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_trust_flags" in result.payload
    assert "unknown_source" in result.payload["_trust_flags"]


@pytest.mark.asyncio
async def test_unknown_source_strict_quarantined(db: EventDB) -> None:
    config = TrustConfig(strictness="strict", known_sources=frozenset())
    ctx = _make_context(db, config)
    cartridge = TrustCartridge()

    event = _make_event(source="unknown-source")
    result = await cartridge.process(event, ctx)

    assert result is None
    rows = await db.list_quarantined()
    assert len(rows) == 1
    assert rows[0]["trust_flags"] == '["unknown_source"]'


@pytest.mark.asyncio
async def test_reject_unknown_level_strict(db: EventDB) -> None:
    config = TrustConfig(strictness="strict", known_sources=frozenset({"known-source"}))
    ctx = _make_context(db, config)
    cartridge = TrustCartridge()

    # Bypass pydantic validation to inject an invalid level
    event = EventEnvelope.model_construct(
        event="test.event",
        source="known-source",
        level=99,  # invalid level
        domain="test",
        payload={},
    )
    result = await cartridge.process(event, ctx)

    assert result is None
    # Should be rejected (not quarantined)
    rows = await db.list_quarantined()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_permissive_accepts_all(db: EventDB) -> None:
    config = TrustConfig(strictness="permissive", known_sources=frozenset())
    ctx = _make_context(db, config)
    cartridge = TrustCartridge()

    # Unknown source + malformed level + no domain — all should pass through
    event = EventEnvelope.model_construct(
        event="test.event",
        source="totally-unknown",
        level=99,
        domain="",
        payload={},
    )
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_trust_flags" not in (result.payload or {})


@pytest.mark.asyncio
async def test_quarantine_writes_db_row(db: EventDB) -> None:
    config = TrustConfig(strictness="strict", known_sources=frozenset())
    ctx = _make_context(db, config)
    cartridge = TrustCartridge()

    event = _make_event(source="intruder")
    result = await cartridge.process(event, ctx)

    assert result is None
    rows = await db.list_quarantined()
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "test.event"
    assert row["source"] == "intruder"
    assert row["reviewed"] == 0
