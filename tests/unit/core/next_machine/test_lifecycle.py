"""Tests for the stamp-driven lifecycle authority."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    apply_authoritative_signal,
)
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


def test_review_verdict_approve_advances_only_immediate_successor() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value
    state.requirements_review.verdict = "approve"
    state.requirements_review.reviewed_at = "2026-01-01T00:00:00+00:00"

    next_phase = apply_authoritative_signal(state, "verdict", phase="requirements_review")

    assert next_phase == LifecyclePhase.TEST_SPEC_BUILD
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.TEST_SPEC_BUILD


def test_review_needs_work_regresses_to_authoring_phase() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.PLAN_REVIEW.value
    state.plan_review.verdict = "needs_work"
    state.plan_review.reviewed_at = "2026-01-01T00:00:00+00:00"
    state.artifacts.implementation_plan.produced_at = "2026-01-01T00:00:00+00:00"

    next_phase = apply_authoritative_signal(state, "verdict", phase="plan_review")

    assert next_phase == LifecyclePhase.PLAN_DRAFTING
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.PLAN_DRAFTING
    assert state.artifacts.implementation_plan.produced_at == ""


def test_adopt_prepare_handoff_phase_skips_requirements_review_without_input() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.DRAFT.value
    state.artifacts.requirements.digest = "req"

    adopted = adopt_prepare_handoff_phase(state)

    assert adopted == LifecyclePhase.TEST_SPEC_BUILD
