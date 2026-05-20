"""Regression tests for canonical lifecycle phase persistence."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.lifecycle import LifecyclePhase, normalize_mark_phase
from teleclaude.types.todos import ApprovalStamp, TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_normalize_mark_phase_clears_downstream_v2_approvals_but_keeps_artifact_history() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REVIEW_APPROVED.value
    state.artifacts.prd.digest = "prd-digest"
    state.artifacts.architecture.digest = "arch-digest"
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.approvals.prd_approved = ApprovalStamp(approved=True, caller_session_id="human-session")
    state.approvals.architecture_approved = ApprovalStamp(approved=True, caller_session_id="human-session")
    state.approvals.plan_approved = ApprovalStamp(approved=True, caller_session_id="human-session")
    state.architecture_review.verdict = "approve"
    state.plan_review.verdict = "approve"
    state.build_start_base_sha = "abc123"
    state.build_review.verdict = "approve"
    state.finalize.status = "ready"

    normalize_mark_phase(state, LifecyclePhase.ARCHITECTURE_DRAFTING)

    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.ARCHITECTURE_DRAFTING
    assert state.artifacts.prd.digest == "prd-digest"
    assert state.artifacts.architecture.digest == "arch-digest"
    assert state.artifacts.implementation_plan.digest == "plan-digest"
    assert state.approvals.prd_approved.approved is True
    assert state.approvals.architecture_approved.approved is False
    assert state.approvals.plan_approved.approved is False
    assert state.architecture_review.verdict == ""
    assert state.plan_review.verdict == ""
    assert state.build_review.verdict == ""
    assert state.finalize.status == "pending"
    assert state.build_start_base_sha == ""


def test_normalize_mark_phase_keeps_canonical_phase_without_legacy_overrides() -> None:
    state = TodoState.defaults()

    normalize_mark_phase(state, LifecyclePhase.PLAN_REVIEW)

    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.PLAN_REVIEW
