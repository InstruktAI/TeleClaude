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
    INPUT_ASSESSMENT = "input_assessment"
    TRIANGULATION = "triangulation"
    REQUIREMENTS_REVIEW = "requirements_review"
    REQUIREMENTS_HUMAN_APPROVAL = "requirements_human_approval"
    TEST_SPEC_BUILD = "test_spec_build"
    TEST_SPEC_REVIEW = "test_spec_review"
    PLAN_DRAFTING = "plan_drafting"
    PLAN_REVIEW = "plan_review"
    GATE = "gate"
    GROUNDING_CHECK = "grounding_check"
    RE_GROUNDING = "re_grounding"
    PREPARED = "prepared"
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
        LifecyclePhase.INPUT_ASSESSMENT,
        LifecyclePhase.TRIANGULATION,
        LifecyclePhase.REQUIREMENTS_REVIEW,
        LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL,
        LifecyclePhase.TEST_SPEC_BUILD,
        LifecyclePhase.TEST_SPEC_REVIEW,
        LifecyclePhase.PLAN_DRAFTING,
        LifecyclePhase.PLAN_REVIEW,
        LifecyclePhase.GATE,
        LifecyclePhase.GROUNDING_CHECK,
        LifecyclePhase.RE_GROUNDING,
        LifecyclePhase.PREPARED,
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
