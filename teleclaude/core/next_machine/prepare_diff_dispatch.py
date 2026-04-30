"""Helpers that augment dispatch messages with artifact-diff commands.

When a review or build is re-routed because an upstream digest changed, the
worker needs to know what changed without the orchestrator having to read or
forward the diff itself. These helpers compute the (label, artifact, old_digest,
new_digest) tuples and append a `telec todo artifacts diff` command line for
each one to the worker's dispatch message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


def append_diff_section(message: str, slug: str, diffs: list[tuple[str, str, str, str]]) -> str:
    """Append a 'Changes since last review/build' section listing diff commands.

    Each diff tuple is (label, artifact_name, old_digest, new_digest). Skips
    entries where either digest is empty or the digests are equal — so callers
    can pass speculative pairs and only the genuinely changed ones surface.
    """
    lines = [
        f"  {label}: telec todo artifacts diff {slug} {artifact} {old} {new}"
        for (label, artifact, old, new) in diffs
        if old and new and old != new
    ]
    if not lines:
        return message
    return message + "\n\nChanges since your last review/build:\n" + "\n".join(lines)


def review_digest_pair(
    artifact_label: str, artifact_name: str, approved_digest: str, current_digest: str
) -> list[tuple[str, str, str, str]]:
    """Return a single-element diff list when a stale approved_digest exists, else empty."""
    if approved_digest and approved_digest != current_digest:
        return [(artifact_label, artifact_name, approved_digest, current_digest)]
    return []


async def build_upstream_diff_pairs(
    todos_db: TodosDb,
    slug: str,
    upstream_digests: dict[str, str],
    expected_upstreams: tuple[tuple[str, str, str], ...],
) -> list[tuple[str, str, str, str]]:
    """Compute diff pairs for each upstream artifact whose recorded digest is stale.

    Each entry in ``expected_upstreams`` is (state_key, label, artifact_name).
    """
    pairs: list[tuple[str, str, str, str]] = []
    for state_key, label, artifact_name in expected_upstreams:
        recorded = upstream_digests.get(state_key, "")
        current = await todos_db.artifact_digest(slug, artifact_name)
        if recorded and current and recorded != current:
            pairs.append((label, artifact_name, recorded, current))
    return pairs
