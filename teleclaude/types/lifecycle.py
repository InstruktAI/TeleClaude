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


class LifecyclePhase(str, Enum):
    """Ordered software-development lifecycle phases."""

    DRAFT = "draft"
    PRD_DRAFTING = "prd_drafting"
    PRD_HUMAN_APPROVAL = "prd_human_approval"
    ARCHITECTURE_DRAFTING = "architecture_drafting"
    ARCHITECTURE_REVIEW = "architecture_review"
    ARCHITECTURE_HUMAN_APPROVAL = "architecture_human_approval"
    TEST_SPECS_DRAFTING = "test_specs_drafting"
    TEST_SPECS_REVIEW = "test_specs_review"
    TEST_SPECS_HUMAN_APPROVAL = "test_specs_human_approval"
    PLAN_DRAFTING = "plan_drafting"
    PLAN_REVIEW = "plan_review"
    PLAN_HUMAN_APPROVAL = "plan_human_approval"
    PREPARED = "prepared"
    BLOCKED = "blocked"
    BUILD_STARTED = "build_started"
    BUILD_COMPLETE = "build_complete"
    REVIEW_CHANGES_REQUESTED = "review_changes_requested"
    REVIEW_APPROVED = "review_approved"
    FINALIZE_READY = "finalize_ready"
    HANDED_OFF = "handed_off"


class LifecycleStage(str, Enum):
    """Stage bucket used for explicit lifecycle reconciliation."""

    PREPARE = "prepare"
    WORK = "work"


LIFECYCLE_PHASE_ORDER: list[LifecyclePhase] = list(LifecyclePhase)

PREPARE_LIFECYCLE_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.DRAFT,
        LifecyclePhase.PRD_DRAFTING,
        LifecyclePhase.PRD_HUMAN_APPROVAL,
        LifecyclePhase.ARCHITECTURE_DRAFTING,
        LifecyclePhase.ARCHITECTURE_REVIEW,
        LifecyclePhase.ARCHITECTURE_HUMAN_APPROVAL,
        LifecyclePhase.TEST_SPECS_DRAFTING,
        LifecyclePhase.TEST_SPECS_REVIEW,
        LifecyclePhase.TEST_SPECS_HUMAN_APPROVAL,
        LifecyclePhase.PLAN_DRAFTING,
        LifecyclePhase.PLAN_REVIEW,
        LifecyclePhase.PLAN_HUMAN_APPROVAL,
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
        LifecyclePhase.HANDED_OFF,
    }
)


__all__ = [
    "LIFECYCLE_PHASE_ORDER",
    "PREPARE_LIFECYCLE_PHASES",
    "WORK_LIFECYCLE_PHASES",
    "LifecyclePhase",
    "LifecycleStage",
]
