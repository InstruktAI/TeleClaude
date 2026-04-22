"""Canonical lifecycle helpers.

This module owns the only authoritative lifecycle rules:

- ``lifecycle_phase`` is the canonical current pointer.
- ``mark-phase`` validates and rewinds the pointer while clearing downstream
  authoritative state.
- authoritative signals advance the pointer by at most one immediate step.

The state machines must read this pointer and dispatch work; they must not
derive or auto-advance lifecycle state on their own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from teleclaude.core.next_machine.git_ops import get_head_commit
from teleclaude.types.todos import ReviewVerdictState, TestSpecReviewState, TodoState


class LifecyclePhase(str, Enum):
    """Ordered software-development lifecycle phases."""

    INPUT_ASSESSMENT = "input_assessment"
    TRIANGULATION = "triangulation"
    REQUIREMENTS_REVIEW = "requirements_review"
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


LIFECYCLE_PHASE_ORDER: list[LifecyclePhase] = list(LifecyclePhase)
PREPARE_LIFECYCLE_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.INPUT_ASSESSMENT,
        LifecyclePhase.TRIANGULATION,
        LifecyclePhase.REQUIREMENTS_REVIEW,
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


def coerce_lifecycle_phase(raw: object) -> LifecyclePhase | None:
    """Return a lifecycle phase enum member for a stored raw value."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return LifecyclePhase(raw)
    except ValueError:
        return None


def lifecycle_phase_index(phase: LifecyclePhase) -> int:
    """Return the stable phase order index."""
    return LIFECYCLE_PHASE_ORDER.index(phase)


def is_prepare_lifecycle_phase(phase: LifecyclePhase) -> bool:
    """Return True when the phase belongs to the prepare lane."""
    return phase in PREPARE_LIFECYCLE_PHASES


def is_work_lifecycle_phase(phase: LifecyclePhase) -> bool:
    """Return True when the phase belongs to the work lane."""
    return phase in WORK_LIFECYCLE_PHASES


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clear_prepare_review(review: ReviewVerdictState | TestSpecReviewState) -> None:
    review.verdict = ""
    review.reviewed_at = ""
    if hasattr(review, "findings_count"):
        review.findings_count = 0


def _clear_build_review(model: TodoState) -> None:
    model.build_review.verdict = ""
    model.build_review.reviewed_at = ""
    model.build_review.dispatch_head = ""


def _reset_finalize(model: TodoState) -> None:
    model.finalize.status = "pending"
    model.finalize.ready_at = ""
    model.finalize.handed_off_at = ""


def _reset_dor(model: TodoState) -> None:
    if model.dor is None:
        return
    model.dor.last_assessed_at = None
    model.dor.score = 0
    model.dor.status = "needs_work"


def _reset_grounding(model: TodoState) -> None:
    model.grounding.valid = False
    model.grounding.last_grounded_at = ""
    model.grounding.invalidated_at = ""
    model.grounding.invalidation_reason = ""
    model.grounding.changed_paths = []


def _reset_after_requirements(model: TodoState) -> None:
    _clear_prepare_review(model.requirements_review)
    model.artifacts.test_specs.produced_at = ""
    _clear_prepare_review(model.test_spec_review)
    model.artifacts.implementation_plan.produced_at = ""
    _clear_prepare_review(model.plan_review)
    _reset_dor(model)
    _reset_grounding(model)
    _clear_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""
    model.build_completed_at = ""


def _reset_after_test_specs(model: TodoState) -> None:
    model.artifacts.test_specs.produced_at = ""
    _clear_prepare_review(model.test_spec_review)
    model.artifacts.implementation_plan.produced_at = ""
    _clear_prepare_review(model.plan_review)
    _reset_dor(model)
    _reset_grounding(model)
    _clear_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""
    model.build_completed_at = ""


def _reset_after_plan(model: TodoState) -> None:
    model.artifacts.implementation_plan.produced_at = ""
    _clear_prepare_review(model.plan_review)
    _reset_dor(model)
    _reset_grounding(model)
    _clear_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""
    model.build_completed_at = ""


def _reset_after_gate(model: TodoState) -> None:
    _reset_dor(model)
    _reset_grounding(model)
    _clear_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""
    model.build_completed_at = ""


def _reset_after_grounding(model: TodoState) -> None:
    _reset_grounding(model)
    _clear_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""
    model.build_completed_at = ""


def phase_is_complete(
    model: TodoState,
    phase: LifecyclePhase,
    *,
    worktree_cwd: str | None = None,
) -> bool:
    """Return True when authoritative state says ``phase`` is complete."""
    _ = worktree_cwd
    if phase in (LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        return bool(model.artifacts.requirements.produced_at) or model.requirements_review.verdict == "skipped"
    if phase == LifecyclePhase.REQUIREMENTS_REVIEW:
        return model.requirements_review.verdict in ("approve", "skipped")
    if phase == LifecyclePhase.TEST_SPEC_BUILD:
        return bool(model.artifacts.test_specs.produced_at)
    if phase == LifecyclePhase.TEST_SPEC_REVIEW:
        return model.test_spec_review.verdict in ("approve", "skipped")
    if phase == LifecyclePhase.PLAN_DRAFTING:
        return bool(model.artifacts.implementation_plan.produced_at)
    if phase == LifecyclePhase.PLAN_REVIEW:
        return model.plan_review.verdict in ("approve", "skipped")
    if phase == LifecyclePhase.GATE:
        return model.dor is not None and model.dor.status == "pass"
    if phase == LifecyclePhase.GROUNDING_CHECK:
        return model.grounding.valid
    if phase == LifecyclePhase.RE_GROUNDING:
        return bool(model.artifacts.implementation_plan.produced_at)
    if phase == LifecyclePhase.PREPARED:
        return False
    if phase == LifecyclePhase.BUILD_STARTED:
        return bool(model.build_completed_at)
    if phase == LifecyclePhase.BUILD_COMPLETE:
        return model.build_review.verdict in ("approve", "changes_requested")
    if phase == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        return False
    if phase == LifecyclePhase.REVIEW_APPROVED:
        return model.finalize.status in ("ready", "handed_off")
    if phase == LifecyclePhase.FINALIZE_READY:
        return model.finalize.status == "handed_off"
    if phase == LifecyclePhase.HANDED_OFF:
        return False
    return False


def _move_to(model: TodoState, target: LifecyclePhase) -> LifecyclePhase:
    model.lifecycle_phase = target.value
    return target


def _apply_authoring_signal(model: TodoState, current: LifecyclePhase, signal: str, now: str) -> LifecyclePhase | None:
    if signal == "requirements_ready" and current in (LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        _reset_after_requirements(model)
        model.artifacts.requirements.produced_at = now
        model.artifacts.requirements.stale = False
        return _move_to(model, LifecyclePhase.REQUIREMENTS_REVIEW)

    if signal == "specs_built" and current == LifecyclePhase.TEST_SPEC_BUILD:
        _reset_after_test_specs(model)
        model.artifacts.test_specs.produced_at = now
        model.artifacts.test_specs.stale = False
        return _move_to(model, LifecyclePhase.TEST_SPEC_REVIEW)

    if signal == "plan_ready" and current in (LifecyclePhase.PLAN_DRAFTING, LifecyclePhase.RE_GROUNDING):
        _reset_after_plan(model)
        model.artifacts.implementation_plan.produced_at = now
        model.artifacts.implementation_plan.stale = False
        return _move_to(model, LifecyclePhase.PLAN_REVIEW)

    return None


def _apply_prepare_signal(model: TodoState, current: LifecyclePhase, signal: str) -> LifecyclePhase | None:
    if signal == "dor" and current == LifecyclePhase.GATE and model.dor is not None and model.dor.status == "pass":
        return _move_to(model, LifecyclePhase.GROUNDING_CHECK)

    if signal == "grounding" and current == LifecyclePhase.GROUNDING_CHECK and model.grounding.valid:
        return _move_to(model, LifecyclePhase.PREPARED)

    if signal == "grounding_invalidated" and current == LifecyclePhase.GROUNDING_CHECK:
        _reset_after_plan(model)
        return _move_to(model, LifecyclePhase.RE_GROUNDING)

    return None


def _apply_build_signal(
    model: TodoState,
    current: LifecyclePhase,
    signal: str,
    now: str,
    worktree_cwd: str | None,
) -> LifecyclePhase | None:
    if signal == "build_started" and current == LifecyclePhase.PREPARED:
        model.build_start_base_sha = get_head_commit(worktree_cwd or "")
        model.build_completed_at = ""
        _clear_build_review(model)
        _reset_finalize(model)
        return _move_to(model, LifecyclePhase.BUILD_STARTED)

    if signal == "build_complete" and current in (
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
    ):
        model.build_completed_at = now
        _reset_finalize(model)
        if current == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
            model.build_review.round += 1
        _clear_build_review(model)
        return _move_to(model, LifecyclePhase.BUILD_COMPLETE)

    return None


def _apply_verdict_signal(model: TodoState, current: LifecyclePhase, phase: str | None) -> LifecyclePhase | None:
    if phase == "requirements_review" and current == LifecyclePhase.REQUIREMENTS_REVIEW:
        if model.requirements_review.verdict in ("approve", "skipped"):
            return _move_to(model, LifecyclePhase.TEST_SPEC_BUILD)
        if model.requirements_review.verdict == "needs_work":
            _reset_after_requirements(model)
            model.artifacts.requirements.produced_at = ""
            return _move_to(model, LifecyclePhase.TRIANGULATION)
        return current

    if phase == "test_spec_review" and current == LifecyclePhase.TEST_SPEC_REVIEW:
        if model.test_spec_review.verdict in ("approve", "skipped"):
            return _move_to(model, LifecyclePhase.PLAN_DRAFTING)
        if model.test_spec_review.verdict == "needs_work":
            _reset_after_test_specs(model)
            return _move_to(model, LifecyclePhase.TEST_SPEC_BUILD)
        return current

    if phase == "plan_review" and current == LifecyclePhase.PLAN_REVIEW:
        if model.plan_review.verdict in ("approve", "skipped"):
            return _move_to(model, LifecyclePhase.GATE)
        if model.plan_review.verdict == "needs_work":
            _reset_after_plan(model)
            return _move_to(model, LifecyclePhase.PLAN_DRAFTING)
        return current

    if phase == "build_review" and current == LifecyclePhase.BUILD_COMPLETE:
        if model.build_review.verdict == "approve":
            return _move_to(model, LifecyclePhase.REVIEW_APPROVED)
        if model.build_review.verdict == "changes_requested":
            model.build_completed_at = ""
            return _move_to(model, LifecyclePhase.REVIEW_CHANGES_REQUESTED)
        return current

    return None


def _apply_finalize_signal(model: TodoState, current: LifecyclePhase, signal: str, now: str) -> LifecyclePhase | None:
    if signal == "finalize_ready" and current == LifecyclePhase.REVIEW_APPROVED and model.finalize.status == "ready":
        return _move_to(model, LifecyclePhase.FINALIZE_READY)

    if signal == "finalize_handed_off" and current == LifecyclePhase.FINALIZE_READY:
        if model.finalize.status == "ready":
            model.finalize.status = "handed_off"
            model.finalize.handed_off_at = now
        if model.finalize.status == "handed_off":
            return _move_to(model, LifecyclePhase.HANDED_OFF)
        return current

    return None


def apply_authoritative_signal(
    model: TodoState,
    signal: str,
    *,
    phase: str | None = None,
    worktree_cwd: str | None = None,
) -> LifecyclePhase:
    """Apply one authoritative signal and advance by at most one step.

    The caller mutates any relevant state first (for example a review verdict
    or DOR value), then this function decides whether the current phase should
    move to its immediate successor.
    """
    current = coerce_lifecycle_phase(model.lifecycle_phase) or LifecyclePhase.INPUT_ASSESSMENT
    now = _now_iso()

    for outcome in (
        _apply_authoring_signal(model, current, signal, now),
        _apply_prepare_signal(model, current, signal),
        _apply_build_signal(model, current, signal, now, worktree_cwd),
        _apply_verdict_signal(model, current, phase),
        _apply_finalize_signal(model, current, signal, now),
    ):
        if outcome is not None:
            return outcome

    return current


def _normalize_prepare_mark_phase(model: TodoState, target: LifecyclePhase) -> None:
    if target in (LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        model.artifacts.requirements.produced_at = ""
        _reset_after_requirements(model)
        return
    if target == LifecyclePhase.REQUIREMENTS_REVIEW:
        _clear_prepare_review(model.requirements_review)
        model.artifacts.test_specs.produced_at = ""
        _clear_prepare_review(model.test_spec_review)
        model.artifacts.implementation_plan.produced_at = ""
        _clear_prepare_review(model.plan_review)
        _reset_dor(model)
        _reset_grounding(model)
        _clear_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = ""
        model.build_completed_at = ""
        return
    if target == LifecyclePhase.TEST_SPEC_BUILD:
        _reset_after_test_specs(model)
        return
    if target == LifecyclePhase.TEST_SPEC_REVIEW:
        _clear_prepare_review(model.test_spec_review)
        model.artifacts.implementation_plan.produced_at = ""
        _clear_prepare_review(model.plan_review)
        _reset_dor(model)
        _reset_grounding(model)
        _clear_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = ""
        model.build_completed_at = ""
        return
    if target == LifecyclePhase.PLAN_DRAFTING:
        _reset_after_plan(model)
        return
    if target == LifecyclePhase.PLAN_REVIEW:
        _clear_prepare_review(model.plan_review)
        _reset_dor(model)
        _reset_grounding(model)
        _clear_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = ""
        model.build_completed_at = ""
        return
    if target == LifecyclePhase.GATE:
        _reset_after_gate(model)
        return
    if target == LifecyclePhase.GROUNDING_CHECK:
        _reset_after_grounding(model)
        return
    if target == LifecyclePhase.RE_GROUNDING:
        _reset_after_plan(model)
        return
    if target == LifecyclePhase.PREPARED:
        _clear_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = ""
        model.build_completed_at = ""


def _normalize_work_mark_phase(model: TodoState, target: LifecyclePhase) -> None:
    if target == LifecyclePhase.BUILD_STARTED:
        model.build_completed_at = ""
        _clear_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = ""
        return
    if target == LifecyclePhase.BUILD_COMPLETE:
        _clear_build_review(model)
        _reset_finalize(model)
        return
    if target == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        _reset_finalize(model)
        return
    if target == LifecyclePhase.REVIEW_APPROVED:
        _reset_finalize(model)
        return


def normalize_mark_phase(
    model: TodoState,
    target: LifecyclePhase,
    *,
    worktree_cwd: str | None = None,
) -> None:
    """Clear current/downstream authority and persist ``target`` as the pointer."""
    _ = worktree_cwd
    model.prepare_phase = ""
    model.work_phase = ""
    if is_prepare_lifecycle_phase(target):
        _normalize_prepare_mark_phase(model, target)
    else:
        _normalize_work_mark_phase(model, target)
    model.lifecycle_phase = target.value


__all__ = [
    "LIFECYCLE_PHASE_ORDER",
    "PREPARE_LIFECYCLE_PHASES",
    "WORK_LIFECYCLE_PHASES",
    "LifecyclePhase",
    "apply_authoritative_signal",
    "coerce_lifecycle_phase",
    "is_prepare_lifecycle_phase",
    "is_work_lifecycle_phase",
    "lifecycle_phase_index",
    "normalize_mark_phase",
    "phase_is_complete",
]
