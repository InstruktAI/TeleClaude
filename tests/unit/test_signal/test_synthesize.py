"""Unit tests for the signal synthesize cartridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext
from teleclaude_events.signal.ai import SynthesisArtifact


def _make_ai_client(synthesis: SynthesisArtifact | None = None) -> MagicMock:
    if synthesis is None:
        synthesis = SynthesisArtifact(
            summary="Key findings from 3 sources on EU AI regulation.",
            key_points=["Draft regulation published", "Industry pushback expected"],
            sources=["https://a.com/1", "https://a.com/2"],
            confidence=0.85,
            recommended_action=None,
        )
    ai = MagicMock()
    ai.summarise = AsyncMock(return_value="Short summary")
    ai.extract_tags = AsyncMock(return_value=["ai", "regulation"])
    ai.embed = AsyncMock(return_value=None)
    ai.synthesise_cluster = AsyncMock(return_value=synthesis)
    return ai


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_synthesize.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


async def _seed_cluster(db: EventDB) -> int:
    """Seed a cluster with 2 members. Returns cluster_id."""
    signal_db = db.signal
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    id1 = await signal_db.insert_signal_item({
        "idempotency_key": "synth-k1",
        "source_id": "src",
        "item_url": "https://a.com/1",
        "raw_title": "AI regulation article 1",
        "summary": "Summary of article one.",
        "tags": ["ai", "regulation"],
        "fetched_at": now_iso,
    })
    id2 = await signal_db.insert_signal_item({
        "idempotency_key": "synth-k2",
        "source_id": "src",
        "item_url": "https://a.com/2",
        "raw_title": "AI regulation article 2",
        "summary": "Summary of article two.",
        "tags": ["ai", "regulation"],
        "fetched_at": now_iso,
    })

    cluster_id = await signal_db.insert_cluster(
        cluster_key="test-cluster-key",
        tags=["ai", "regulation"],
        is_burst=False,
        is_novel=True,
        summary="Cluster of AI regulation news",
        member_ids=[id1, id2],
    )
    await signal_db.assign_items_to_cluster([id1, id2], cluster_id)
    return cluster_id


@pytest.mark.asyncio
async def test_synthesize_produces_ready_event(db: EventDB) -> None:
    from company.cartridges.signal.synthesize import SignalSynthesizeCartridge, SynthesizeConfig

    cluster_id = await _seed_cluster(db)
    ai = _make_ai_client()
    signal_db = db.signal
    config = SynthesizeConfig(fetch_full_content=False)
    cartridge = SignalSynthesizeCartridge(config=config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="signal.cluster.formed",
        source="signal-cluster",
        level=EventLevel.OPERATIONAL,
        domain="signal",
        payload={"cluster_id": cluster_id, "member_count": 2, "tags": ["ai"], "is_burst": False, "is_novel": True, "summary": "..."},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    result = await cartridge.process(env, context)

    assert result is not None
    assert result.event == "signal.synthesis.ready"
    assert result.payload["cluster_id"] == cluster_id
    assert "synthesis" in result.payload
    synthesis = result.payload["synthesis"]
    assert "summary" in synthesis
    assert "key_points" in synthesis
    assert "sources" in synthesis
    assert "confidence" in synthesis


@pytest.mark.asyncio
async def test_synthesize_passes_through_non_cluster_event(db: EventDB) -> None:
    from company.cartridges.signal.synthesize import SignalSynthesizeCartridge, SynthesizeConfig

    ai = _make_ai_client()
    signal_db = db.signal
    config = SynthesizeConfig(fetch_full_content=False)
    cartridge = SignalSynthesizeCartridge(config=config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="signal.ingest.received",
        source="signal-ingest",
        level=EventLevel.OPERATIONAL,
        domain="signal",
        payload={"source_id": "src"},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    result = await cartridge.process(env, context)

    assert result is env  # passed through unchanged
    ai.synthesise_cluster.assert_not_called()


@pytest.mark.asyncio
async def test_synthesize_deduplicates_near_identical_summaries(db: EventDB) -> None:
    """Near-duplicate summaries should be collapsed before AI call."""
    from company.cartridges.signal.synthesize import SignalSynthesizeCartridge, SynthesizeConfig

    signal_db = db.signal
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert 3 items where 2 have nearly identical summaries
    id1 = await signal_db.insert_signal_item({
        "idempotency_key": "dedup-k1",
        "source_id": "src",
        "item_url": "https://a.com/1",
        "raw_title": "AI article",
        "summary": "EU announces new artificial intelligence regulation framework proposal.",
        "tags": ["ai"],
        "fetched_at": now_iso,
    })
    id2 = await signal_db.insert_signal_item({
        "idempotency_key": "dedup-k2",
        "source_id": "src2",
        "item_url": "https://b.com/1",
        "raw_title": "AI article copy",
        "summary": "EU announces new artificial intelligence regulation framework proposal.",  # identical
        "tags": ["ai"],
        "fetched_at": now_iso,
    })
    id3 = await signal_db.insert_signal_item({
        "idempotency_key": "dedup-k3",
        "source_id": "src3",
        "item_url": "https://c.com/1",
        "raw_title": "Different AI article",
        "summary": "Industry groups push back against strict AI regulation measures.",
        "tags": ["ai"],
        "fetched_at": now_iso,
    })

    cluster_id = await signal_db.insert_cluster(
        cluster_key="dedup-cluster-key",
        tags=["ai"],
        is_burst=False,
        is_novel=False,
        summary="AI regulation cluster",
        member_ids=[id1, id2, id3],
    )
    await signal_db.assign_items_to_cluster([id1, id2, id3], cluster_id)

    ai = _make_ai_client()
    config = SynthesizeConfig(fetch_full_content=False)
    cartridge = SignalSynthesizeCartridge(config=config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="signal.cluster.formed",
        source="signal-cluster",
        level=EventLevel.OPERATIONAL,
        domain="signal",
        payload={"cluster_id": cluster_id, "member_count": 3, "tags": ["ai"], "is_burst": False, "is_novel": False, "summary": "..."},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    await cartridge.process(env, context)

    # synthesise_cluster called with 2 items (dedup removed the near-identical one)
    call_args = ai.synthesise_cluster.call_args[0][0]
    assert len(call_args) == 2


@pytest.mark.asyncio
async def test_synthesize_description_truncated(db: EventDB) -> None:
    from company.cartridges.signal.synthesize import SignalSynthesizeCartridge, SynthesizeConfig

    long_summary = "X" * 500
    synthesis = SynthesisArtifact(
        summary=long_summary,
        key_points=[],
        sources=[],
        confidence=0.9,
    )
    cluster_id = await _seed_cluster(db)
    ai = _make_ai_client(synthesis=synthesis)
    signal_db = db.signal
    config = SynthesizeConfig(fetch_full_content=False)
    cartridge = SignalSynthesizeCartridge(config=config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="signal.cluster.formed",
        source="signal-cluster",
        level=EventLevel.OPERATIONAL,
        domain="signal",
        payload={"cluster_id": cluster_id, "member_count": 2, "tags": [], "is_burst": False, "is_novel": False, "summary": "..."},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    result = await cartridge.process(env, context)

    assert result is not None
    assert len(result.description) <= 200
