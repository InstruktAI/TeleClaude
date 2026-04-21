"""Canonical lifecycle phase helpers for the next-work machines.

The lifecycle now has one authoritative phase field. Workers and automation
write evidence; the machine advances ``lifecycle_phase`` when the current
phase's completion condition is satisfied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD
from teleclaude.core.next_machine.build_gates import run_build_gates
from teleclaude.core.next_machine.git_ops import get_head_commit
from teleclaude.git import GitCommandError, Repo
from teleclaude.types.todos import TodoState


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


def _has_build_commits_beyond(worktree_cwd: str, base_ref: str) -> bool:
    """Return True when the worktree has commits beyond ``base_ref``."""
    if not worktree_cwd or not base_ref:
        return False
    try:
        repo = Repo(worktree_cwd)
        log_output = repo.git.log("--oneline", f"{base_ref}..HEAD")
        return bool(log_output.strip())
    except (GitCommandError, OSError):
        return False


def _has_build_commits_beyond_main(worktree_cwd: str) -> bool:
    """Return True when the worktree branch has commits ahead of main."""
    if not worktree_cwd:
        return False
    try:
        repo = Repo(worktree_cwd)
        base = repo.git.merge_base("HEAD", "main").strip()
        log_output = repo.git.log("--oneline", f"{base}..HEAD")
        return bool(log_output.strip())
    except (GitCommandError, OSError):
        return False


def _build_complete_reached(model: TodoState, worktree_cwd: str | None) -> bool:
    """Return True when build output exists and passes gates."""
    if not worktree_cwd:
        return False
    base_sha = model.build_start_base_sha
    if base_sha:
        has_new_commits = _has_build_commits_beyond(worktree_cwd, base_sha)
    else:
        has_new_commits = _has_build_commits_beyond_main(worktree_cwd)
    if not has_new_commits:
        return False
    gates_passed, _ = run_build_gates(worktree_cwd, "")
    return bool(gates_passed)


def phase_is_complete(
    model: TodoState,
    phase: LifecyclePhase,
    *,
    worktree_cwd: str | None = None,
) -> bool:
    """Return True when the given phase's completion condition is satisfied."""
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
        dor = model.dor
        if dor is None:
            return False
        return dor.status == "pass" or dor.score >= DOR_READY_THRESHOLD
    if phase == LifecyclePhase.GROUNDING_CHECK:
        return model.grounding.valid
    if phase == LifecyclePhase.RE_GROUNDING:
        return bool(model.artifacts.implementation_plan.produced_at)
    if phase == LifecyclePhase.PREPARED:
        return False
    if phase == LifecyclePhase.BUILD_STARTED:
        return _build_complete_reached(model, worktree_cwd)
    if phase == LifecyclePhase.BUILD_COMPLETE:
        return model.build_review.verdict in ("approve", "changes_requested")
    if phase == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        baseline = model.build_review.baseline_commit
        head_sha = get_head_commit(worktree_cwd or "")
        return bool(baseline and head_sha and head_sha != baseline)
    if phase == LifecyclePhase.REVIEW_APPROVED:
        return model.finalize.status in ("ready", "handed_off")
    if phase == LifecyclePhase.FINALIZE_READY:
        return model.finalize.status == "handed_off"
    if phase == LifecyclePhase.HANDED_OFF:
        return False
    return False


def next_phase_after(model: TodoState, phase: LifecyclePhase) -> LifecyclePhase:
    """Return the next lifecycle phase after a completed phase."""
    if phase in (LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        return LifecyclePhase.REQUIREMENTS_REVIEW
    if phase == LifecyclePhase.REQUIREMENTS_REVIEW:
        return LifecyclePhase.TEST_SPEC_BUILD
    if phase == LifecyclePhase.TEST_SPEC_BUILD:
        return LifecyclePhase.TEST_SPEC_REVIEW
    if phase == LifecyclePhase.TEST_SPEC_REVIEW:
        return LifecyclePhase.PLAN_DRAFTING
    if phase == LifecyclePhase.PLAN_DRAFTING:
        return LifecyclePhase.PLAN_REVIEW
    if phase == LifecyclePhase.PLAN_REVIEW:
        return LifecyclePhase.GATE
    if phase == LifecyclePhase.GATE:
        return LifecyclePhase.GROUNDING_CHECK
    if phase == LifecyclePhase.GROUNDING_CHECK:
        return LifecyclePhase.PREPARED
    if phase == LifecyclePhase.RE_GROUNDING:
        return LifecyclePhase.PLAN_REVIEW
    if phase == LifecyclePhase.BUILD_STARTED:
        return LifecyclePhase.BUILD_COMPLETE
    if phase == LifecyclePhase.BUILD_COMPLETE:
        if model.build_review.verdict == "approve":
            return LifecyclePhase.REVIEW_APPROVED
        if model.build_review.verdict == "changes_requested":
            return LifecyclePhase.REVIEW_CHANGES_REQUESTED
    if phase == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        return LifecyclePhase.BUILD_COMPLETE
    if phase == LifecyclePhase.REVIEW_APPROVED:
        return LifecyclePhase.FINALIZE_READY
    if phase == LifecyclePhase.FINALIZE_READY:
        return LifecyclePhase.HANDED_OFF
    return phase


def advance_until_blocked(model: TodoState, *, worktree_cwd: str | None = None) -> LifecyclePhase:
    """Advance the canonical lifecycle phase while the current phase is complete."""
    current = coerce_lifecycle_phase(model.lifecycle_phase) or LifecyclePhase.INPUT_ASSESSMENT
    while phase_is_complete(model, current, worktree_cwd=worktree_cwd):
        next_phase = next_phase_after(model, current)
        if next_phase == current:
            break
        if next_phase == LifecyclePhase.BUILD_STARTED and worktree_cwd and not model.build_start_base_sha:
            model.build_start_base_sha = get_head_commit(worktree_cwd)
        model.lifecycle_phase = next_phase.value
        current = next_phase
    return current


def furthest_reached_phase(model: TodoState, *, worktree_cwd: str | None = None) -> LifecyclePhase:
    """Return the highest lifecycle phase evidenced by the current state."""
    phase = LifecyclePhase.INPUT_ASSESSMENT
    while phase_is_complete(model, phase, worktree_cwd=worktree_cwd):
        next_phase = next_phase_after(model, phase)
        if next_phase == phase:
            break
        phase = next_phase
    return phase


def _reset_finalize(model: TodoState) -> None:
    model.finalize.status = "pending"
    model.finalize.ready_at = ""
    model.finalize.handed_off_at = ""


def _reset_build_review(model: TodoState) -> None:
    model.build_review.verdict = ""
    model.build_review.reviewed_at = ""
    model.build_review.dispatch_head = ""


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
    model.requirements_review.verdict = ""
    model.requirements_review.reviewed_at = ""
    model.artifacts.test_specs.produced_at = ""
    model.test_spec_review.verdict = ""
    model.test_spec_review.reviewed_at = ""
    model.artifacts.implementation_plan.produced_at = ""
    model.plan_review.verdict = ""
    model.plan_review.reviewed_at = ""
    _reset_dor(model)
    _reset_grounding(model)
    _reset_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""


def _reset_after_test_specs(model: TodoState) -> None:
    model.artifacts.test_specs.produced_at = ""
    model.test_spec_review.verdict = ""
    model.test_spec_review.reviewed_at = ""
    model.artifacts.implementation_plan.produced_at = ""
    model.plan_review.verdict = ""
    model.plan_review.reviewed_at = ""
    _reset_dor(model)
    _reset_grounding(model)
    _reset_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""


def _reset_after_plan(model: TodoState) -> None:
    model.artifacts.implementation_plan.produced_at = ""
    model.plan_review.verdict = ""
    model.plan_review.reviewed_at = ""
    _reset_dor(model)
    _reset_grounding(model)
    _reset_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""


def _reset_after_gate(model: TodoState) -> None:
    _reset_dor(model)
    _reset_grounding(model)
    _reset_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""


def _reset_after_grounding(model: TodoState) -> None:
    _reset_grounding(model)
    _reset_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""


def _normalize_prepare_mark_phase(model: TodoState, target: LifecyclePhase) -> None:
    if target in (LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        model.artifacts.requirements.produced_at = ""
        _reset_after_requirements(model)
        return
    if target == LifecyclePhase.REQUIREMENTS_REVIEW:
        _reset_after_requirements(model)
        return
    if target == LifecyclePhase.TEST_SPEC_BUILD:
        _reset_after_test_specs(model)
        return
    if target == LifecyclePhase.TEST_SPEC_REVIEW:
        model.test_spec_review.verdict = ""
        model.test_spec_review.reviewed_at = ""
        _reset_after_plan(model)
        return
    if target == LifecyclePhase.PLAN_DRAFTING:
        _reset_after_plan(model)
        return
    if target == LifecyclePhase.PLAN_REVIEW:
        model.plan_review.verdict = ""
        model.plan_review.reviewed_at = ""
        _reset_after_gate(model)
        return
    if target == LifecyclePhase.GATE:
        _reset_after_gate(model)
        return
    if target == LifecyclePhase.GROUNDING_CHECK:
        _reset_after_grounding(model)
        return
    if target == LifecyclePhase.RE_GROUNDING:
        model.artifacts.implementation_plan.produced_at = ""
        model.plan_review.verdict = ""
        model.plan_review.reviewed_at = ""
        _reset_dor(model)
        _reset_after_grounding(model)
        return
    if target == LifecyclePhase.PREPARED:
        _reset_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = ""


def _normalize_work_mark_phase(model: TodoState, target: LifecyclePhase, worktree_cwd: str | None) -> None:
    if target == LifecyclePhase.BUILD_STARTED:
        _reset_build_review(model)
        _reset_finalize(model)
        model.build_start_base_sha = get_head_commit(worktree_cwd or "")
        return
    if target == LifecyclePhase.BUILD_COMPLETE:
        _reset_build_review(model)
        _reset_finalize(model)
        head_sha = get_head_commit(worktree_cwd or "")
        if head_sha:
            model.build_review.baseline_commit = head_sha
            model.build_start_base_sha = head_sha
        return
    if target == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        head_sha = get_head_commit(worktree_cwd or "")
        if head_sha:
            model.build_review.baseline_commit = head_sha
        model.build_review.dispatch_head = ""
        _reset_finalize(model)
        return
    if target == LifecyclePhase.REVIEW_APPROVED:
        _reset_finalize(model)
        return
    if target == LifecyclePhase.FINALIZE_READY:
        model.finalize.status = "ready"
        if not model.finalize.ready_at:
            model.finalize.ready_at = _now_iso()
        model.finalize.handed_off_at = ""
        return
    if target == LifecyclePhase.HANDED_OFF:
        now = _now_iso()
        model.finalize.status = "handed_off"
        if not model.finalize.ready_at:
            model.finalize.ready_at = now
        if not model.finalize.handed_off_at:
            model.finalize.handed_off_at = now


def normalize_mark_phase(
    model: TodoState,
    target: LifecyclePhase,
    *,
    worktree_cwd: str | None = None,
) -> None:
    """Rewrite lifecycle-completion markers so ``target`` becomes authoritative."""
    model.prepare_phase = ""
    model.work_phase = ""
    if is_prepare_lifecycle_phase(target):
        _normalize_prepare_mark_phase(model, target)
    else:
        _normalize_work_mark_phase(model, target, worktree_cwd)
    model.lifecycle_phase = target.value


__all__ = [
    "LIFECYCLE_PHASE_ORDER",
    "PREPARE_LIFECYCLE_PHASES",
    "WORK_LIFECYCLE_PHASES",
    "LifecyclePhase",
    "advance_until_blocked",
    "coerce_lifecycle_phase",
    "furthest_reached_phase",
    "is_prepare_lifecycle_phase",
    "is_work_lifecycle_phase",
    "lifecycle_phase_index",
    "next_phase_after",
    "normalize_mark_phase",
    "phase_is_complete",
]
