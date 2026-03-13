"""Signal cluster algorithm — tag-overlap and embedding-based grouping."""

from __future__ import annotations

import hashlib
import math

from pydantic import BaseModel


class ClusteringConfig(BaseModel):
    window_seconds: int = 900
    min_cluster_size: int = 2
    burst_threshold: int = 5
    novelty_overlap_hours: int = 24
    tag_overlap_min: int = 1
    embedding_similarity_threshold: float = 0.80
    singleton_promote_after_seconds: int = 3600


def group_by_tags(items: list[dict[str, object]], min_overlap: int = 1) -> list[list[dict[str, object]]]:
    """Group items by shared tag overlap using union-find."""
    n = len(items)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    # Build tag → item indices mapping
    tag_to_indices: dict[str, list[int]] = {}
    for idx, item in enumerate(items):
        for tag in item.get("tags", []):  # type: ignore[union-attr]
            tag_str = str(tag)
            tag_to_indices.setdefault(tag_str, []).append(idx)

    # Count shared tags between pairs and union if >= min_overlap
    pair_overlap: dict[tuple[int, int], int] = {}
    for indices in tag_to_indices.values():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = indices[i], indices[j]
                key = (min(a, b), max(a, b))
                pair_overlap[key] = pair_overlap.get(key, 0) + 1

    for (a, b), count in pair_overlap.items():
        if count >= min_overlap:
            union(a, b)

    # Collect groups
    groups: dict[int, list[dict[str, object]]] = {}
    for idx, item in enumerate(items):
        root = find(idx)
        groups.setdefault(root, []).append(item)

    return list(groups.values())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def refine_by_embeddings(group: list[dict[str, object]], threshold: float) -> list[list[dict[str, object]]]:
    """Split a group into sub-groups based on embedding cosine similarity.

    Falls back to returning the original group as-is if embeddings are missing.
    """
    embeddings: list[list[float] | None] = [
        item.get("embedding")
        for item in group  # type: ignore[misc]
    ]

    # Degrade gracefully if any embedding is missing
    if any(e is None for e in embeddings):
        return [group]

    n = len(group)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            ei = embeddings[i]
            ej = embeddings[j]
            if ei is not None and ej is not None:
                sim = _cosine_similarity(ei, ej)
                if sim >= threshold:
                    union(i, j)

    sub_groups: dict[int, list[dict[str, object]]] = {}
    for idx, item in enumerate(group):
        root = find(idx)
        sub_groups.setdefault(root, []).append(item)

    return list(sub_groups.values())


def detect_burst(group: list[dict[str, object]], threshold: int) -> bool:
    return len(group) >= threshold


def detect_novelty(group_tags: list[str], recent_tags: list[str]) -> bool:
    return not bool(set(group_tags) & set(recent_tags))


def build_cluster_key(item_idempotency_keys: list[str]) -> str:
    """SHA-256 of sorted joined item idempotency keys → hex[:16]."""
    combined = ":".join(sorted(item_idempotency_keys))
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
