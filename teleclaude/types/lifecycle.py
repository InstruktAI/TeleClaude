"""Lifecycle phase enums and stage groupings — pure types, no behavior.

This is a leaf module. It owns the canonical phase identifiers so that
lightweight consumers (e.g. ``todos_db._upcycle``, hooks, the TUI) can
reference them without pulling in the state-machine helpers in
``next_machine.lifecycle``.

State-transition logic, validation helpers, and authoritative-signal
application live in ``teleclaude.core.next_machine.lifecycle``, which
imports these types from here and adds the behavior.
"""

from __future__ import annotations

from enum import Enum

LEGACY_LIFECYCLE_PHASE_NORMALIZATION: dict[str, str] = {
    "architecture_human_approval": "architecture_review",
    "plan_human_approval": "plan_review",
    # The test-specs phase was removed (doc-first model: Gherkin lives in the
    # feature spec authored at intake). Rows persisted on a test-specs phase or
    # its old human-approval alias re-adopt from the architecture gate, from
    # which prepare re-derives the real phase via reviewer verdicts/skips.
    "test_specs_drafting": "architecture_review",
    "test_specs_review": "architecture_review",
    "test_specs_human_approval": "architecture_review",
}


class LifecyclePhase(str, Enum):
    """Ordered software-development lifecycle phases."""

    UNKINDED = "unkinded"
    KIND_PROPOSED = "kind_proposed"
    DRAFT = "draft"
    PRD_DRAFTING = "prd_drafting"
    PRD_HUMAN_APPROVAL = "prd_human_approval"
    ARCHITECTURE_DRAFTING = "architecture_drafting"
    ARCHITECTURE_REVIEW = "architecture_review"
    PLAN_DRAFTING = "plan_drafting"
    PLAN_REVIEW = "plan_review"
    PREPARED = "prepared"
    BLOCKED = "blocked"
    BUILD_STARTED = "build_started"
    BUILD_COMPLETE = "build_complete"
    REVIEW_CHANGES_REQUESTED = "review_changes_requested"
    REVIEW_APPROVED = "review_approved"
    FINALIZE_READY = "finalize_ready"


class LifecycleStage(str, Enum):
    """Stage bucket used for explicit lifecycle reconciliation."""

    PREPARE = "prepare"
    WORK = "work"


LIFECYCLE_PHASE_ORDER: list[LifecyclePhase] = list(LifecyclePhase)

PREPARE_LIFECYCLE_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.UNKINDED,
        LifecyclePhase.KIND_PROPOSED,
        LifecyclePhase.DRAFT,
        LifecyclePhase.PRD_DRAFTING,
        LifecyclePhase.PRD_HUMAN_APPROVAL,
        LifecyclePhase.ARCHITECTURE_DRAFTING,
        LifecyclePhase.ARCHITECTURE_REVIEW,
        LifecyclePhase.PLAN_DRAFTING,
        LifecyclePhase.PLAN_REVIEW,
        LifecyclePhase.PREPARED,
        LifecyclePhase.BLOCKED,
    }
)

WORK_LIFECYCLE_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.BUILD_COMPLETE,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.REVIEW_APPROVED,
        LifecyclePhase.FINALIZE_READY,
    }
)


__all__ = [
    "LEGACY_LIFECYCLE_PHASE_NORMALIZATION",
    "LIFECYCLE_PHASE_ORDER",
    "PREPARE_LIFECYCLE_PHASES",
    "WORK_LIFECYCLE_PHASES",
    "LifecyclePhase",
    "LifecycleStage",
]
