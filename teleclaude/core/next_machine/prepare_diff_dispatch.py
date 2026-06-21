"""Helpers that augment dispatch messages with artifact-diff commands and
explicit dispatch reasons.

Re-entry is the base case for prepare's downstream-artifact dispatches:
prepare-plan, review-architecture, review-specs, review-plan,
and drift analysis. The orchestrator must tell the worker *why* it was
dispatched so the worker can pick the right behavior (produce fresh, fix
findings, refresh against upstream changes, or verify alignment when
provenance is missing). These helpers are the single seam where that reason
is injected into the dispatch message, alongside any concrete
``telec todo artifacts diff`` commands the worker needs to inspect.

Intake dispatches do not pass through these helpers — they gate on the
absence of a PRD artifact and derive behavior from artifact state rather than
a reason header.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


class DispatchReason(StrEnum):
    """Classifies why a prepare worker was dispatched.

    Workers select their behavior from this value. The orchestrator never
    omits the reason — silence on the dispatch contract is the failure mode
    that produces silent overwrites of valid existing artifacts.
    """

    FRESH = "fresh"
    """No prior artifact exists; produce from scratch."""

    SEEDED = "seeded"
    """A `--plan`-created plan is present at first entry with no prior review;
    treat it as the draft basis, not an oracle, and ground it fully."""

    SUBSTANTIVE_DRIFT = "substantive-drift"
    """Code under the plan's referenced paths drifted materially; re-derive the
    existing plan against the change and preserve unaffected tasks."""

    FINDINGS_FIX = "findings-fix"
    """A needs_work verdict requires targeted revision against findings."""

    UPSTREAM_CHANGED = "upstream-changed"
    """A recorded upstream digest does not match current; refresh incrementally."""

    PROVENANCE_MISSING = "provenance-missing"
    """An artifact exists but its upstream provenance is empty; verify alignment
    against current upstream and update only what no longer pins behavior."""


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


def format_dispatch_reason(
    message: str,
    slug: str,
    reason: DispatchReason,
    diffs: list[tuple[str, str, str, str]] | None = None,
) -> str:
    """Prepend an explicit dispatch-reason header to a worker message.

    Workers read the reason header to pick their behavior. When ``diffs`` are
    supplied, the existing 'Changes since' section is appended below the reason
    so the worker has the concrete diff commands needed to inspect what changed.
    """
    header = f"Dispatch reason: {reason.value}"
    body = f"{header}\n\n{message}"
    if diffs:
        return append_diff_section(body, slug, diffs)
    return body


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
