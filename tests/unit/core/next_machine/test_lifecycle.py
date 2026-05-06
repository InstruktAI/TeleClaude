"""Tests for the stamp-driven lifecycle authority."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    apply_authoritative_signal,
    derive_build_status,
    derive_review_status,
    is_in_prepare_lane,
    is_ready_for_work,
    is_settled_ok_phase,
    phase_is_complete,
    reconcile_lifecycle_phase,
)
from teleclaude.types.lifecycle import LifecycleStage
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_requirements_ready_advances_only_one_step() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.TRIANGULATION.value
    state.artifacts.input.digest = "input"

    next_phase = apply_authoritative_signal(state, "requirements_ready")

    assert next_phase == LifecyclePhase.REQUIREMENTS_REVIEW
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.REQUIREMENTS_REVIEW
    assert state.artifacts.requirements.produced_at


def test_requirements_ready_without_input_skips_requirements_review() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.INPUT_ASSESSMENT.value

    next_phase = apply_authoritative_signal(state, "requirements_ready")

    assert next_phase == LifecyclePhase.TEST_SPEC_BUILD
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.TEST_SPEC_BUILD
    assert state.requirements_review.verdict == "skipped"
    assert state.requirements_review.reviewed_at


def test_plan_ready_advances_plan_drafting_to_plan_review() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.PLAN_DRAFTING.value

    next_phase = apply_authoritative_signal(state, "plan_ready")

    assert next_phase == LifecyclePhase.PLAN_REVIEW
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.PLAN_REVIEW
    assert state.artifacts.implementation_plan.produced_at


def test_build_complete_advances_changes_requested_back_to_build_complete() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REVIEW_CHANGES_REQUESTED.value

    next_phase = apply_authoritative_signal(state, "build_complete")

    assert next_phase == LifecyclePhase.BUILD_COMPLETE
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.BUILD_COMPLETE
    assert state.build_completed_at


def test_work_reconcile_does_not_infer_build_complete_from_commits() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.BUILD_STARTED.value

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("teleclaude.core.next_machine.lifecycle.get_head_commit", lambda _cwd: "head")
        next_phase = reconcile_lifecycle_phase(
            state,
            LifecycleStage.WORK,
            worktree_cwd="/repo/trees/my-slug",
        )

    assert next_phase == LifecyclePhase.BUILD_STARTED


def test_finalize_handed_off_advances_finalize_ready_to_handed_off() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.FINALIZE_READY.value
    state.finalize.status = "ready"

    next_phase = apply_authoritative_signal(state, "finalize_handed_off")

    assert next_phase == LifecyclePhase.HANDED_OFF
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.HANDED_OFF
    assert state.finalize.status == "handed_off"
    assert state.finalize.handed_off_at


def test_review_verdict_approve_advances_only_immediate_successor() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value
    state.requirements_review.verdict = "approve"
    state.requirements_review.reviewed_at = "2026-01-01T00:00:00+00:00"

    next_phase = apply_authoritative_signal(state, "verdict", phase="requirements_review")

    assert next_phase == LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL


def test_review_needs_work_stays_in_review_phase_for_fix_forward() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.PLAN_REVIEW.value
    state.plan_review.verdict = "needs_work"
    state.plan_review.reviewed_at = "2026-01-01T00:00:00+00:00"
    state.artifacts.implementation_plan.produced_at = "2026-01-01T00:00:00+00:00"

    next_phase = apply_authoritative_signal(state, "verdict", phase="plan_review")

    assert next_phase == LifecyclePhase.PLAN_REVIEW
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.PLAN_REVIEW
    assert state.artifacts.implementation_plan.produced_at == "2026-01-01T00:00:00+00:00"


def test_adopt_prepare_handoff_phase_skips_requirements_review_without_input() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.DRAFT.value
    state.artifacts.requirements.digest = "req"

    adopted = adopt_prepare_handoff_phase(state)

    assert adopted == LifecyclePhase.TEST_SPEC_BUILD


def test_gate_phase_completion_uses_plan_review_verdict() -> None:
    state = TodoState.defaults()
    state.plan_review.verdict = "approve"

    assert phase_is_complete(state, LifecyclePhase.GATE)


def test_adopt_prepare_handoff_phase_ignores_legacy_dor_status() -> None:
    state = TodoState.defaults()
    state.dor = TodoState.model_validate({"dor": {"score": 8, "status": "pass"}}).dor

    adopted = adopt_prepare_handoff_phase(state)

    assert adopted == LifecyclePhase.INPUT_ASSESSMENT


def test_dor_signal_no_longer_advances_gate() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.GATE.value
    state.dor = TodoState.model_validate({"dor": {"score": 8, "status": "pass"}}).dor

    next_phase = apply_authoritative_signal(state, "dor")

    assert next_phase == LifecyclePhase.GATE
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.GATE


# ── High-level predicates and projections ───────────────────────────────────
# These five helpers consolidate readiness/lane/projection logic that was
# previously duplicated across the work state machine, slug resolution, the
# TUI, the roadmap projection, and resource validation.


class TestIsReadyForWork:
    def test_bug_is_always_ready(self) -> None:
        ready, reason = is_ready_for_work(kind="bug", lifecycle_phase=None)
        assert ready
        assert reason == ""

    def test_bug_ready_even_with_pre_prepared_phase(self) -> None:
        ready, _ = is_ready_for_work(kind="bug", lifecycle_phase="grounding_check")
        assert ready

    def test_pre_prepared_todo_blocked(self) -> None:
        ready, reason = is_ready_for_work(kind="todo", lifecycle_phase="grounding_check")
        assert not ready
        assert "before 'prepared'" in reason

    def test_prepared_todo_ready(self) -> None:
        ready, reason = is_ready_for_work(kind="todo", lifecycle_phase="prepared")
        assert ready
        assert reason == ""

    @pytest.mark.parametrize(
        "phase",
        [
            "build_started",
            "build_complete",
            "review_changes_requested",
            "review_approved",
            "finalize_ready",
            "handed_off",
        ],
    )
    def test_at_or_beyond_prepared_ready(self, phase: str) -> None:
        """Resume mid-build/mid-review must succeed."""
        ready, _ = is_ready_for_work(kind="todo", lifecycle_phase=phase)
        assert ready

    def test_unknown_phase_blocked(self) -> None:
        ready, reason = is_ready_for_work(kind="todo", lifecycle_phase="not_a_real_phase")
        assert not ready
        assert "unknown lifecycle_phase" in reason

    def test_none_phase_blocked(self) -> None:
        ready, reason = is_ready_for_work(kind="todo", lifecycle_phase=None)
        assert not ready
        assert "unknown lifecycle_phase" in reason


class TestIsInPrepareLane:
    @pytest.mark.parametrize(
        "phase",
        [
            "draft",
            "input_assessment",
            "triangulation",
            "requirements_review",
            "test_spec_build",
            "test_spec_review",
            "plan_drafting",
            "plan_review",
            "gate",
            "grounding_check",
            "re_grounding",
            "prepared",
        ],
    )
    def test_all_prepare_lane_phases_match(self, phase: str) -> None:
        assert is_in_prepare_lane(phase)

    @pytest.mark.parametrize(
        "phase",
        ["build_started", "build_complete", "review_approved", "finalize_ready", "handed_off"],
    )
    def test_post_prepared_phases_excluded(self, phase: str) -> None:
        assert not is_in_prepare_lane(phase)

    def test_none_returns_false(self) -> None:
        assert not is_in_prepare_lane(None)

    def test_unknown_returns_false(self) -> None:
        assert not is_in_prepare_lane("not_a_real_phase")


class TestIsSettledOkPhase:
    @pytest.mark.parametrize("phase", ["prepared", "review_approved"])
    def test_settled_ok(self, phase: str) -> None:
        assert is_settled_ok_phase(phase)

    @pytest.mark.parametrize(
        "phase",
        ["build_started", "build_complete", "review_changes_requested", "draft", "input_assessment"],
    )
    def test_other_phases_not_settled(self, phase: str) -> None:
        assert not is_settled_ok_phase(phase)

    def test_none_not_settled(self) -> None:
        assert not is_settled_ok_phase(None)


class TestDeriveBuildStatus:
    def test_draft_returns_none(self) -> None:
        assert derive_build_status("build_started", is_draft=True, is_delivered=False) is None

    def test_delivered_returns_none(self) -> None:
        assert derive_build_status("build_complete", is_draft=False, is_delivered=True) is None

    def test_pre_build_returns_none(self) -> None:
        assert derive_build_status("prepared", is_draft=False, is_delivered=False) is None

    def test_build_started_returns_started(self) -> None:
        assert derive_build_status("build_started", is_draft=False, is_delivered=False) == "started"

    @pytest.mark.parametrize(
        "phase",
        ["build_complete", "review_changes_requested", "review_approved", "finalize_ready", "handed_off"],
    )
    def test_post_build_returns_complete(self, phase: str) -> None:
        assert derive_build_status(phase, is_draft=False, is_delivered=False) == "complete"


class TestDeriveReviewStatus:
    def test_draft_returns_none(self) -> None:
        assert derive_review_status("build_complete", is_draft=True, is_delivered=False) is None

    def test_delivered_returns_none(self) -> None:
        assert derive_review_status("review_approved", is_draft=False, is_delivered=True) is None

    def test_pre_review_returns_none(self) -> None:
        assert derive_review_status("build_started", is_draft=False, is_delivered=False) is None

    def test_build_complete_returns_pending(self) -> None:
        assert derive_review_status("build_complete", is_draft=False, is_delivered=False) == "pending"

    def test_changes_requested(self) -> None:
        assert (
            derive_review_status("review_changes_requested", is_draft=False, is_delivered=False) == "changes_requested"
        )

    @pytest.mark.parametrize("phase", ["review_approved", "finalize_ready", "handed_off"])
    def test_approved_phases(self, phase: str) -> None:
        assert derive_review_status(phase, is_draft=False, is_delivered=False) == "approved"
