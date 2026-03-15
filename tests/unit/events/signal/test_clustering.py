"""Characterization tests for teleclaude.events.signal.clustering."""

from __future__ import annotations

from typing import cast

from teleclaude.events.signal.clustering import (
    ClusteringConfig,
    build_cluster_key,
    detect_burst,
    detect_novelty,
    group_by_tags,
    refine_by_embeddings,
)
from teleclaude.events.signal.db import SignalItemPayload


def _item(url: str, tags: list[str] | None = None, embedding: list[float] | None = None) -> SignalItemPayload:
    result = cast(SignalItemPayload, {"item_url": url, "tags": tags or []})
    if embedding is not None:
        result["embedding"] = embedding
    return result


def test_clustering_config_defaults() -> None:
    config = ClusteringConfig()
    assert config.window_seconds == 900
    assert config.min_cluster_size == 2
    assert config.burst_threshold == 5
    assert config.novelty_overlap_hours == 24
    assert config.tag_overlap_min == 1
    assert config.embedding_similarity_threshold == 0.80
    assert config.singleton_promote_after_seconds == 3600


def test_group_by_tags_empty_input_returns_empty() -> None:
    result = group_by_tags([])
    assert result == []


def test_group_by_tags_single_item_returns_singleton_group() -> None:
    item = _item("http://a.com", tags=["tech"])
    result = group_by_tags([item])
    assert len(result) == 1
    assert result[0] == [item]


def test_group_by_tags_groups_items_with_shared_tag() -> None:
    items = [
        _item("http://a.com", tags=["tech", "ai"]),
        _item("http://b.com", tags=["ai", "ml"]),
        _item("http://c.com", tags=["sports"]),
    ]
    result = group_by_tags(items)
    # Items a and b share "ai" → one group; c is separate
    assert len(result) == 2
    sizes = sorted(len(g) for g in result)
    assert sizes == [1, 2]


def test_group_by_tags_all_disjoint_returns_singletons() -> None:
    items = [_item("http://a.com", tags=["x"]), _item("http://b.com", tags=["y"])]
    result = group_by_tags(items)
    assert len(result) == 2


def test_group_by_tags_no_tags_each_item_is_own_group() -> None:
    items = [_item("http://a.com"), _item("http://b.com")]
    result = group_by_tags(items)
    assert len(result) == 2


def test_refine_by_embeddings_fallback_when_missing_embeddings() -> None:
    group = [_item("http://a.com"), _item("http://b.com")]
    result = refine_by_embeddings(group, threshold=0.8)
    assert result == [group]


def test_refine_by_embeddings_merges_similar_items() -> None:
    group = [
        _item("http://a.com", embedding=[1.0, 0.0]),
        _item("http://b.com", embedding=[1.0, 0.0]),
    ]
    result = refine_by_embeddings(group, threshold=0.99)
    assert len(result) == 1
    assert len(result[0]) == 2


def test_refine_by_embeddings_splits_dissimilar_items() -> None:
    group = [
        _item("http://a.com", embedding=[1.0, 0.0]),
        _item("http://b.com", embedding=[0.0, 1.0]),
    ]
    result = refine_by_embeddings(group, threshold=0.99)
    assert len(result) == 2


def test_detect_burst_above_threshold_returns_true() -> None:
    items = [_item(f"http://{i}.com") for i in range(5)]
    assert detect_burst(items, threshold=5) is True


def test_detect_burst_below_threshold_returns_false() -> None:
    items = [_item(f"http://{i}.com") for i in range(4)]
    assert detect_burst(items, threshold=5) is False


def test_detect_novelty_no_overlap_returns_true() -> None:
    assert detect_novelty(["ai", "tech"], ["sports", "finance"]) is True


def test_detect_novelty_overlap_returns_false() -> None:
    assert detect_novelty(["ai", "tech"], ["tech", "science"]) is False


def test_build_cluster_key_is_deterministic() -> None:
    keys = ["key1", "key2", "key3"]
    result1 = build_cluster_key(keys)
    result2 = build_cluster_key(keys)
    assert result1 == result2


def test_build_cluster_key_order_independent() -> None:
    result1 = build_cluster_key(["a", "b", "c"])
    result2 = build_cluster_key(["c", "a", "b"])
    assert result1 == result2


def test_build_cluster_key_returns_sixteen_hex_chars() -> None:
    result = build_cluster_key(["key1"])
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


def test_build_cluster_key_different_inputs_produce_different_keys() -> None:
    key1 = build_cluster_key(["a"])
    key2 = build_cluster_key(["b"])
    assert key1 != key2
