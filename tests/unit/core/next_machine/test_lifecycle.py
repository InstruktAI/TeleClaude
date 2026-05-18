"""Tests for v2 prepare lifecycle derivation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    apply_authoritative_signal,
    coerce_lifecycle_phase,
    is_in_prepare_lane,
    is_ready_for_work,
    is_settled_ok_phase,
    phase_is_complete,
    prepare_blockers,
    reconcile_lifecycle_phase,
)
from teleclaude.types.lifecycle import LifecycleStage
from teleclaude.types.todos import ApprovalStamp, DriftReviewedStamp, SkipStamp, TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def _approved(at: str = "2026-01-01T00:00:00+00:00") -> ApprovalStamp:
    return ApprovalStamp(approved=True, approved_at=at, caller_session_id="session-human")


def _base_feature() -> TodoState:
    state = TodoState.defaults()
    state.kind = "feature"
    state.artifacts.input.digest = "input"
    return state


def test_no_artifacts_stays_draft() -> None:
    state = TodoState.defaults()

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.DRAFT


def test_input_without_prd_enters_prd_drafting() -> None:
    state = _base_feature()

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PRD_DRAFTING


def test_prd_without_human_approval_waits_for_human(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.approvals.prd_approved = ApprovalStamp(approved=True, caller_session_id="system-session")
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "system:worker"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PRD_HUMAN_APPROVAL


def test_prd_human_approval_advances_to_architecture(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.approvals.prd_approved = _approved()
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.ARCHITECTURE_DRAFTING


def test_architecture_skip_routes_to_test_specs(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.approvals.prd_approved = _approved()
    state.approvals.architecture_skipped = SkipStamp(reason="small", skipped_at="now")
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.TEST_SPECS_DRAFTING


def test_both_optional_layers_skipped_routes_to_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.approvals.prd_approved = _approved()
    state.approvals.architecture_skipped = SkipStamp(reason="small", skipped_at="now")
    state.approvals.test_specs_skipped = SkipStamp(reason="covered", skipped_at="now")
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PLAN_DRAFTING


def test_legacy_requirements_fallback_can_reconcile_to_prepared() -> None:
    state = _base_feature()
    state.artifacts.requirements.digest = "requirements"
    state.requirements_review.verdict = "approve"
    state.approvals.architecture_skipped = SkipStamp(reason="legacy", skipped_at="now")
    state.approvals.test_specs_skipped = SkipStamp(reason="legacy", skipped_at="now")
    state.artifacts.implementation_plan.digest = "plan"
    state.plan_review.verdict = "approve"

    assert prepare_blockers(state) == []
    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PREPARED


def test_architecture_review_approval_advances_to_test_specs(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.architecture.digest = "architecture"
    state.approvals.prd_approved = _approved()
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.ARCHITECTURE_REVIEW

    state.architecture_review.verdict = "approve"
    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.TEST_SPECS_DRAFTING


def test_architecture_review_approval_advances_to_plan_when_test_specs_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.architecture.digest = "architecture"
    state.approvals.prd_approved = _approved()
    state.approvals.test_specs_skipped = SkipStamp(reason="covered", skipped_at="now")
    state.architecture_review.verdict = "approve"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PLAN_DRAFTING


def test_test_specs_review_approval_advances_to_existing_plan_review(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.architecture.digest = "architecture"
    state.artifacts.test_specs.digest = "specs"
    state.artifacts.implementation_plan.digest = "plan"
    state.approvals.prd_approved = _approved()
    state.architecture_review.verdict = "approve"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.TEST_SPECS_REVIEW

    state.test_spec_review.verdict = "approve"
    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PLAN_REVIEW


def test_test_specs_review_approval_advances_to_plan_drafting(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.architecture.digest = "architecture"
    state.artifacts.test_specs.digest = "specs"
    state.approvals.prd_approved = _approved()
    state.architecture_review.verdict = "approve"
    state.test_spec_review.verdict = "approve"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PLAN_DRAFTING


def test_plan_review_approval_advances_to_prepared(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.architecture.digest = "architecture"
    state.artifacts.test_specs.digest = "specs"
    state.artifacts.implementation_plan.digest = "plan"
    state.approvals.prd_approved = _approved()
    state.architecture_review.verdict = "approve"
    state.test_spec_review.verdict = "approve"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    state.plan_review.verdict = "approve"
    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PREPARED


def test_substantive_drift_blocks_after_plan_review_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.approvals.prd_approved = _approved()
    state.approvals.architecture_skipped = SkipStamp(reason="small", skipped_at="now")
    state.approvals.test_specs_skipped = SkipStamp(reason="covered", skipped_at="now")
    state.artifacts.implementation_plan.digest = "plan"
    state.plan_review.verdict = "approve"
    state.approvals.drift_reviewed["prd"] = DriftReviewedStamp(
        verdict="substantive",
        reason="changed API",
        stamped_at="now",
    )
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.BLOCKED


def test_pending_git_drift_blocks_after_plan_review_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.prd.codebase_sha_at_write = "base"
    state.artifacts.prd.referenced_paths = ["src/feature.py"]
    state.approvals.prd_approved = _approved()
    state.approvals.architecture_skipped = SkipStamp(reason="small", skipped_at="now")
    state.approvals.test_specs_skipped = SkipStamp(reason="covered", skipped_at="now")
    state.artifacts.implementation_plan.digest = "plan"
    state.artifacts.implementation_plan.codebase_sha_at_write = "head"
    state.plan_review.verdict = "approve"
    repo = MagicMock()
    repo.git.rev_parse.return_value = "head"
    repo.git.log.return_value = "src/feature.py\n"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        phase = adopt_prepare_handoff_phase(state, repo_root="/repo")

    assert phase is LifecyclePhase.BLOCKED


def test_review_changes_requested_without_remediation_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.artifacts.architecture.digest = "architecture"
    state.artifacts.architecture.produced_at = "2026-01-01T00:00:00+00:00"
    state.approvals.prd_approved = _approved()
    state.architecture_review.verdict = "needs_work"
    state.architecture_review.reviewed_at = "2026-01-02T00:00:00+00:00"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.BLOCKED


def test_missing_required_upstream_artifact_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = ""
    state.artifacts.implementation_plan.digest = "plan"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.BLOCKED


def test_unupcyclable_state_blocks() -> None:
    state = TodoState.defaults()
    state.schema_version = 2

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.BLOCKED


def test_prepped_kind_stays_prepared() -> None:
    state = TodoState.defaults()
    state.kind = "prepped"
    state.lifecycle_phase = LifecyclePhase.PREPARED.value

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PREPARED


def test_refactor_kind_is_plan_only() -> None:
    state = TodoState.defaults()
    state.kind = "refactor"

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PLAN_DRAFTING

    state.artifacts.implementation_plan.digest = "plan"
    state.plan_review.verdict = "approve"
    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.PREPARED


def test_migration_kind_plan_review_approval_respects_blockers() -> None:
    state = TodoState.defaults()
    state.kind = "migration"
    state.artifacts.implementation_plan.digest = "plan"
    state.plan_review.verdict = "approve"
    state.schema_version = 2

    assert adopt_prepare_handoff_phase(state) is LifecyclePhase.BLOCKED


def test_legacy_raw_phases_normalize_for_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_state = TodoState.defaults().model_dump()
    raw_state["kind"] = "feature"
    raw_state["lifecycle_phase"] = "architecture_human_approval"
    raw_state["artifacts"]["input"]["digest"] = "input"
    raw_state["artifacts"]["prd"]["digest"] = "prd"
    raw_state["artifacts"]["architecture"]["digest"] = "architecture"
    raw_state["approvals"]["prd_approved"]["approved"] = True
    raw_state["approvals"]["prd_approved"]["caller_session_id"] = "session-human"
    raw_state["architecture_review"]["verdict"] = "approve"
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    state = TodoState.model_validate(raw_state)

    assert coerce_lifecycle_phase("architecture_human_approval") is LifecyclePhase.ARCHITECTURE_REVIEW
    assert state.lifecycle_phase == LifecyclePhase.ARCHITECTURE_REVIEW.value
    assert reconcile_lifecycle_phase(state, LifecycleStage.PREPARE) is LifecyclePhase.TEST_SPECS_DRAFTING


def test_legacy_test_specs_and_plan_raw_phases_normalize() -> None:
    assert coerce_lifecycle_phase("test_specs_human_approval") is LifecyclePhase.TEST_SPECS_REVIEW
    assert coerce_lifecycle_phase("plan_human_approval") is LifecyclePhase.PLAN_REVIEW


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

    next_phase = reconcile_lifecycle_phase(state, LifecycleStage.WORK, worktree_cwd="/repo/trees/my-slug")

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


def test_phase_completion_uses_v2_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _base_feature()
    state.artifacts.prd.digest = "prd"
    state.approvals.prd_approved = _approved()
    monkeypatch.setattr(
        "teleclaude.core.next_machine.lifecycle._session_principal", lambda _session_id: "human:mo@example.com"
    )

    assert phase_is_complete(state, LifecyclePhase.PRD_DRAFTING)
    assert phase_is_complete(state, LifecyclePhase.PRD_HUMAN_APPROVAL)


class TestIsReadyForWork:
    def test_bug_is_always_ready(self) -> None:
        ready, reason = is_ready_for_work(kind="bug", lifecycle_phase=None)
        assert ready
        assert reason == ""

    def test_prepared_todo_ready(self) -> None:
        ready, reason = is_ready_for_work(kind="feature", lifecycle_phase="prepared")
        assert ready
        assert reason == ""

    def test_pre_prepared_todo_blocked(self, snapshot: SnapshotAssertion) -> None:
        ready, reason = is_ready_for_work(kind="feature", lifecycle_phase="plan_review")
        assert not ready
        assert reason == snapshot


class TestIsInPrepareLane:
    def test_prepare_phase_returns_true(self) -> None:
        assert is_in_prepare_lane("prd_drafting")

    def test_work_phase_returns_false(self) -> None:
        assert not is_in_prepare_lane("build_started")


class TestIsSettledOkPhase:
    def test_prepared_and_review_approved_are_settled_ok(self) -> None:
        assert is_settled_ok_phase("prepared")
        assert is_settled_ok_phase("review_approved")

    def test_build_started_is_not_settled_ok(self) -> None:
        assert not is_settled_ok_phase("build_started")
