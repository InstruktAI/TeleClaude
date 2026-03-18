"""Signal cluster algorithm — tag-overlap and embedding-based grouping."""

from __future__ import annotations

import hashlib
import math
from typing import cast

from pydantic import BaseModel

from teleclaude.events.signal.db import SignalItemPayload


class ClusteringConfig(BaseModel):
    """Configurable thresholds for tag and embedding based clustering."""

    window_seconds: int = 900
    min_cluster_size: int = 2
    burst_threshold: int = 5
    novelty_overlap_hours: int = 24
    tag_overlap_min: int = 1
    embedding_similarity_threshold: float = 0.80
    singleton_promote_after_seconds: int = 3600


def _find_root(parent: list[int], index: int) -> int:
    """Return the union-find root for one item index."""
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _union_roots(parent: list[int], left: int, right: int) -> None:
    """Merge the sets containing two item indices."""
    parent[_find_root(parent, left)] = _find_root(parent, right)


def _group_items_by_parent(
    items: list[SignalItemPayload],
    parent: list[int],
) -> list[list[SignalItemPayload]]:
    """Collect items into groups keyed by their union-find root."""
    groups: dict[int, list[SignalItemPayload]] = {}
    for idx, item in enumerate(items):
        root = _find_root(parent, idx)
        groups.setdefault(root, []).append(item)
    return list(groups.values())


def _build_tag_index(items: list[SignalItemPayload]) -> dict[str, list[int]]:
    """Build a mapping of tag to item indices."""
    tag_to_indices: dict[str, list[int]] = {}
    for idx, item in enumerate(items):
        for tag in item.get("tags", []):
            tag_to_indices.setdefault(str(tag), []).append(idx)
    return tag_to_indices


def _build_pair_overlap(tag_to_indices: dict[str, list[int]]) -> dict[tuple[int, int], int]:
    """Count shared tags for each item pair."""
    pair_overlap: dict[tuple[int, int], int] = {}
    for indices in tag_to_indices.values():
        for i, left in enumerate(indices):
            for right in indices[i + 1 :]:
                key = (min(left, right), max(left, right))
                pair_overlap[key] = pair_overlap.get(key, 0) + 1
    return pair_overlap


def _union_embedding_matches(
    parent: list[int],
    embeddings: list[list[float]],
    threshold: float,
) -> None:
    """Union embedding-similar items in-place."""
    for i, embedding in enumerate(embeddings):
        for j, other_embedding in enumerate(embeddings[i + 1 :], start=i + 1):
            if _cosine_similarity(embedding, other_embedding) >= threshold:
                _union_roots(parent, i, j)


def group_by_tags(items: list[SignalItemPayload], min_overlap: int = 1) -> list[list[SignalItemPayload]]:
    """Group items by shared tag overlap using union-find."""
    if not items:
        return []

    parent = list(range(len(items)))
    pair_overlap = _build_pair_overlap(_build_tag_index(items))

    for (left, right), count in pair_overlap.items():
        if count >= min_overlap:
            _union_roots(parent, left, right)
    return _group_items_by_parent(items, parent)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def refine_by_embeddings(group: list[SignalItemPayload], threshold: float) -> list[list[SignalItemPayload]]:
    """Split a group into sub-groups based on embedding cosine similarity.

    Falls back to returning the original group as-is if embeddings are missing.
    """
    embedding_candidates = [item.get("embedding") for item in group]
    if any(embedding is None for embedding in embedding_candidates):
        return [group]
    embeddings = [cast(list[float], embedding) for embedding in embedding_candidates]
    parent = list(range(len(group)))
    _union_embedding_matches(parent, embeddings, threshold)
    return _group_items_by_parent(group, parent)


def detect_burst(group: list[SignalItemPayload], threshold: int) -> bool:
    """Return whether a grouped cluster size meets the burst threshold."""
    return len(group) >= threshold


def detect_novelty(group_tags: list[str], recent_tags: list[str]) -> bool:
    """Return whether a tag set is novel relative to recent cluster tags."""
    return not bool(set(group_tags) & set(recent_tags))


def build_cluster_key(item_idempotency_keys: list[str]) -> str:
    """SHA-256 of sorted joined item idempotency keys → hex[:16]."""
    combined = ":".join(sorted(item_idempotency_keys))
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
