"""Unit tests for cluster algorithm and cluster cartridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext
from teleclaude_events.signal.clustering import (
    ClusteringConfig,
    build_cluster_key,
    detect_burst,
    detect_novelty,
    group_by_tags,
    refine_by_embeddings,
)


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_group_by_tags_groups_items_sharing_tag() -> None:
    items = [
        {"id": 1, "tags": ["ai", "regulation"], "idempotency_key": "k1"},
        {"id": 2, "tags": ["ai", "safety"], "idempotency_key": "k2"},
        {"id": 3, "tags": ["cooking", "recipes"], "idempotency_key": "k3"},
    ]
    groups = group_by_tags(items, min_overlap=1)
    # Items 1 and 2 share "ai", item 3 is separate
    assert len(groups) == 2
    group_sizes = sorted(len(g) for g in groups)
    assert group_sizes == [1, 2]


def test_group_by_tags_no_overlap_all_singletons() -> None:
    items = [
        {"id": 1, "tags": ["alpha"], "idempotency_key": "k1"},
        {"id": 2, "tags": ["beta"], "idempotency_key": "k2"},
        {"id": 3, "tags": ["gamma"], "idempotency_key": "k3"},
    ]
    groups = group_by_tags(items, min_overlap=1)
    assert len(groups) == 3


def test_group_by_tags_empty_list() -> None:
    assert group_by_tags([], min_overlap=1) == []


def test_detect_burst_fires_at_threshold() -> None:
    items = [{"id": i} for i in range(5)]
    assert detect_burst(items, threshold=5) is True
    assert detect_burst(items, threshold=6) is False
    assert detect_burst(items[:-1], threshold=5) is False


def test_detect_novelty_true_when_no_overlap() -> None:
    group_tags = ["ai-safety", "regulation"]
    recent_tags = ["cooking", "sports"]
    assert detect_novelty(group_tags, recent_tags) is True


def test_detect_novelty_false_when_overlap_exists() -> None:
    group_tags = ["ai-safety", "regulation"]
    recent_tags = ["regulation", "policy"]
    assert detect_novelty(group_tags, recent_tags) is False


def test_detect_novelty_empty_recent_is_novel() -> None:
    assert detect_novelty(["ai"], []) is True


def test_build_cluster_key_deterministic() -> None:
    keys = ["k3", "k1", "k2"]
    result1 = build_cluster_key(keys)
    result2 = build_cluster_key(["k1", "k2", "k3"])  # different order
    assert result1 == result2  # sorted before hashing
    assert len(result1) == 16


def test_refine_by_embeddings_falls_back_when_missing() -> None:
    items = [
        {"id": 1, "tags": ["ai"], "embedding": None},
        {"id": 2, "tags": ["ai"], "embedding": None},
    ]
    # Should return original group as-is (degraded mode)
    result = refine_by_embeddings(items, threshold=0.80)
    assert len(result) == 1
    assert result[0] == items


def test_refine_by_embeddings_splits_dissimilar() -> None:
    # Two items with orthogonal embeddings should be split
    items = [
        {"id": 1, "tags": ["ai"], "embedding": [1.0, 0.0]},
        {"id": 2, "tags": ["ai"], "embedding": [0.0, 1.0]},  # orthogonal
    ]
    result = refine_by_embeddings(items, threshold=0.80)
    assert len(result) == 2  # split into two singletons


# ---------------------------------------------------------------------------
# Cluster cartridge integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_cluster.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


async def _insert_items(signal_db, items_data: list[dict]) -> list[int]:
    """Insert signal items and return their IDs."""
    ids = []
    for payload in items_data:
        row_id = await signal_db.insert_signal_item(payload)
        ids.append(row_id)
    return ids


def _make_ai_client(summary: str = "Cluster summary") -> MagicMock:
    ai = MagicMock()
    ai.summarise = AsyncMock(return_value=summary)
    ai.extract_tags = AsyncMock(return_value=["test"])
    ai.embed = AsyncMock(return_value=None)
    return ai


@pytest.mark.asyncio
async def test_cluster_cartridge_emits_cluster_formed(db: EventDB) -> None:
    from company.cartridges.signal.cluster import SignalClusterCartridge

    signal_db = db.signal
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert 2 items sharing a tag (minimum cluster size = 2)
    await _insert_items(signal_db, [
        {"idempotency_key": "k1", "source_id": "src", "item_url": "https://a.com/1",
         "raw_title": "AI news 1", "summary": "Summary 1", "tags": ["ai", "regulation"],
         "fetched_at": now_iso},
        {"idempotency_key": "k2", "source_id": "src", "item_url": "https://a.com/2",
         "raw_title": "AI news 2", "summary": "Summary 2", "tags": ["ai", "safety"],
         "fetched_at": now_iso},
    ])

    ai = _make_ai_client()
    config = ClusteringConfig(min_cluster_size=2, burst_threshold=10, window_seconds=7200)
    cartridge = SignalClusterCartridge(config=config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)
    count = await cartridge.cluster_pass(context)

    assert count == 1
    assert len(emitted) == 1
    assert emitted[0].event == "signal.cluster.formed"
    assert emitted[0].payload["member_count"] == 2
    assert "ai" in emitted[0].payload["tags"]


@pytest.mark.asyncio
async def test_cluster_cartridge_singletons_not_clustered(db: EventDB) -> None:
    from company.cartridges.signal.cluster import SignalClusterCartridge

    signal_db = db.signal
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    # Items with no shared tags
    await _insert_items(signal_db, [
        {"idempotency_key": "k1", "source_id": "src", "item_url": "https://a.com/1",
         "raw_title": "Cooking", "summary": "Cooking", "tags": ["cooking"],
         "fetched_at": now_iso},
        {"idempotency_key": "k2", "source_id": "src", "item_url": "https://a.com/2",
         "raw_title": "Sports", "summary": "Sports", "tags": ["sports"],
         "fetched_at": now_iso},
    ])

    ai = _make_ai_client()
    config = ClusteringConfig(min_cluster_size=2, burst_threshold=10, window_seconds=7200)
    cartridge = SignalClusterCartridge(config=config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)
    count = await cartridge.cluster_pass(context)

    assert count == 0
    assert len(emitted) == 0


@pytest.mark.asyncio
async def test_cluster_cartridge_passes_ingest_event_through(db: EventDB) -> None:
    from company.cartridges.signal.cluster import SignalClusterCartridge

    signal_db = db.signal
    ai = _make_ai_client()
    config = ClusteringConfig(min_cluster_size=2, window_seconds=7200)
    cartridge = SignalClusterCartridge(config=config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="signal.ingest.received",
        source="signal-ingest",
        level=EventLevel.OPERATIONAL,
        domain="signal",
        payload={"source_id": "src", "item_url": "https://a.com/1"},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    result = await cartridge.process(env, context)

    assert result is env  # passed through unchanged


@pytest.mark.asyncio
async def test_cluster_cartridge_non_ingest_event_passes_through(db: EventDB) -> None:
    from company.cartridges.signal.cluster import SignalClusterCartridge

    signal_db = db.signal
    ai = _make_ai_client()
    config = ClusteringConfig(min_cluster_size=2, window_seconds=7200)
    cartridge = SignalClusterCartridge(config=config, ai=ai, signal_db=signal_db)

    env = EventEnvelope(
        event="deployment.started",
        source="deploy",
        level=EventLevel.WORKFLOW,
        domain="deployment",
        payload={},
    )
    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[])
    result = await cartridge.process(env, context)

    assert result is env


@pytest.mark.asyncio
async def test_cluster_cartridge_detects_burst(db: EventDB) -> None:
    from company.cartridges.signal.cluster import SignalClusterCartridge

    signal_db = db.signal
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert 5 items with the same tag
    for i in range(5):
        await _insert_items(signal_db, [
            {"idempotency_key": f"k{i}", "source_id": "src", "item_url": f"https://a.com/{i}",
             "raw_title": f"AI news {i}", "summary": f"Summary {i}", "tags": ["ai"],
             "fetched_at": now_iso},
        ])

    ai = _make_ai_client()
    config = ClusteringConfig(min_cluster_size=2, burst_threshold=5, window_seconds=7200)
    cartridge = SignalClusterCartridge(config=config, ai=ai, signal_db=signal_db)

    emitted: list[EventEnvelope] = []

    async def mock_emit(env: EventEnvelope) -> None:
        emitted.append(env)

    context = PipelineContext(catalog=EventCatalog(), db=db, push_callbacks=[], emit=mock_emit)
    await cartridge.cluster_pass(context)

    assert len(emitted) == 1
    assert emitted[0].payload["is_burst"] is True
