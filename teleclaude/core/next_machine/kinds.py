"""Todo kind → lifecycle entry-phase routing — the single source of truth.

A kind names where a work-unit enters the lifecycle. ``KIND_ENTRY_PHASE`` is the
one table; the frozenset views below are projections of it for membership checks
in the state machines.
"""

from __future__ import annotations

from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todo_kind import TODO_KIND_BUG, TODO_KIND_CHANGE, TODO_KIND_FEATURE, TODO_KIND_TASK

KIND_BUG = TODO_KIND_BUG
KIND_CHANGE = TODO_KIND_CHANGE
KIND_FEATURE = TODO_KIND_FEATURE
KIND_TASK = TODO_KIND_TASK

# Single source of truth: the phase each kind enters the lifecycle at.
#   feature → author a PRD (full prepare)
#   change  → draft a plan directly (no PRD; intent is the input artifact)
#   bug     → skip prepare; the fix lane investigates from the input artifact
#   task    → non-SDLC; no automatic pickup, but prepared for task-plan work
KIND_ENTRY_PHASE: dict[str, LifecyclePhase] = {
    KIND_FEATURE: LifecyclePhase.PRD_DRAFTING,
    KIND_CHANGE: LifecyclePhase.PLAN_DRAFTING,
    KIND_BUG: LifecyclePhase.PREPARED,
    KIND_TASK: LifecyclePhase.PREPARED,
}

# Projections of KIND_ENTRY_PHASE for membership checks. Derived, never edited directly.
FEATURE_PREPARE_KINDS = frozenset(k for k, p in KIND_ENTRY_PHASE.items() if p is LifecyclePhase.PRD_DRAFTING)
PLAN_ONLY_PREPARE_KINDS = frozenset(k for k, p in KIND_ENTRY_PHASE.items() if p is LifecyclePhase.PLAN_DRAFTING)
FAST_TRACK_PREPARED_KINDS = frozenset(k for k, p in KIND_ENTRY_PHASE.items() if p is LifecyclePhase.PREPARED)
PLAN_WITHOUT_INTENT_UPSTREAM_KINDS = PLAN_ONLY_PREPARE_KINDS

# Pre-collapse SDLC kinds map to their canonical lifecycle successors.
_LEGACY_KIND_MAP = {
    "todo": KIND_FEATURE,
    "draft": KIND_FEATURE,
    "refactor": KIND_CHANGE,
    "migration": KIND_CHANGE,
    "chore": KIND_CHANGE,
    "prepped": KIND_CHANGE,
    "built": KIND_CHANGE,
}


def canonical_kind(raw: str | None) -> str:
    """Normalize a present kind to the canonical {feature, change, bug, task}.

    Current kinds pass through; known pre-collapse kinds map to their successor.
    An empty or unknown kind is corruption and raises (fail-fast) — a caller that
    legitimately backfills a missing kind on a pre-collapse row does so explicitly
    (see ``upcycle_state_dict``), never through a silent fallback here.
    """
    if raw is not None and raw in KIND_ENTRY_PHASE:
        return raw
    mapped = _LEGACY_KIND_MAP.get(raw) if raw else None
    if mapped is not None:
        return mapped
    raise ValueError(f"unknown todo kind: {raw!r}")
