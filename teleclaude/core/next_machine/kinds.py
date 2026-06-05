"""Todo kind → lifecycle entry-phase routing — the single source of truth.

A kind names where a work-unit enters the lifecycle. ``KIND_ENTRY_PHASE`` is the
one table; the frozenset views below are projections of it for membership checks
in the state machines.
"""

from __future__ import annotations

from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todo_kind import TODO_KIND_BUG, TODO_KIND_CHANGE, TODO_KIND_FEATURE

KIND_BUG = TODO_KIND_BUG
KIND_CHANGE = TODO_KIND_CHANGE
KIND_FEATURE = TODO_KIND_FEATURE

# Single source of truth: the phase each kind enters the lifecycle at.
#   feature → author a PRD (full prepare)
#   change  → draft a plan directly (no PRD; intent is the input artifact)
#   bug     → skip prepare; the fix lane investigates from the input artifact
KIND_ENTRY_PHASE: dict[str, LifecyclePhase] = {
    KIND_FEATURE: LifecyclePhase.PRD_DRAFTING,
    KIND_CHANGE: LifecyclePhase.PLAN_DRAFTING,
    KIND_BUG: LifecyclePhase.PREPARED,
}

# Projections of KIND_ENTRY_PHASE for membership checks. Derived, never edited directly.
FEATURE_PREPARE_KINDS = frozenset(k for k, p in KIND_ENTRY_PHASE.items() if p is LifecyclePhase.PRD_DRAFTING)
PLAN_ONLY_PREPARE_KINDS = frozenset(k for k, p in KIND_ENTRY_PHASE.items() if p is LifecyclePhase.PLAN_DRAFTING)
FAST_TRACK_PREPARED_KINDS = frozenset(k for k, p in KIND_ENTRY_PHASE.items() if p is LifecyclePhase.PREPARED)
PLAN_WITHOUT_INTENT_UPSTREAM_KINDS = PLAN_ONLY_PREPARE_KINDS

# Pre-collapse kinds mapped onto the canonical {feature, change, bug} set.
_LEGACY_KIND_MAP = {
    "todo": KIND_FEATURE,
    "draft": KIND_FEATURE,
    "refactor": KIND_CHANGE,
    "migration": KIND_CHANGE,
    "chore": KIND_CHANGE,
    "prepped": KIND_CHANGE,
}


def canonical_kind(raw: str | None) -> str:
    """Normalize any historical or current kind to the canonical {feature, change, bug}."""
    if not raw:
        return KIND_FEATURE
    if raw in KIND_ENTRY_PHASE:
        return raw
    return _LEGACY_KIND_MAP.get(raw, KIND_FEATURE)
