# guard: no-companion
"""Regression tests for canonical lifecycle phase persistence."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.lifecycle import LifecyclePhase, normalize_mark_phase
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_normalize_mark_phase_clears_downstream_stamps_but_keeps_artifact_history() -> None:
    """mark-phase preserves artifact history and clears only downstream authority."""
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REVIEW_APPROVED.value
    state.artifacts.requirements.digest = "req-digest"
    state.artifacts.requirements.produced_at = "2026-01-01T00:00:00+00:00"
    state.artifacts.test_specs.digest = "spec-digest"
    state.artifacts.test_specs.produced_at = "2026-01-02T00:00:00+00:00"
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.produced_at = "2026-01-03T00:00:00+00:00"
    state.test_spec_review.verdict = "approve"
    state.test_spec_review.reviewed_at = "2026-01-04T00:00:00+00:00"
    state.plan_review.verdict = "approve"
    state.plan_review.reviewed_at = "2026-01-05T00:00:00+00:00"
    state.dor = TodoState.model_validate({"dor": {}}).dor
    assert state.dor is not None
    state.dor.status = "pass"
    state.dor.score = 8
    state.grounding.valid = True
    state.grounding.last_grounded_at = "2026-01-06T00:00:00+00:00"
    state.build_start_base_sha = "abc123"
    state.build_review.verdict = "approve"
    state.build_review.reviewed_at = "2026-01-07T00:00:00+00:00"
    state.finalize.status = "ready"
    state.finalize.ready_at = "2026-01-08T00:00:00+00:00"

    normalize_mark_phase(state, LifecyclePhase.TEST_SPEC_BUILD)

    assert state.lifecycle_phase == LifecyclePhase.TEST_SPEC_BUILD.value
    assert state.artifacts.requirements.digest == "req-digest"
    assert state.artifacts.requirements.produced_at == "2026-01-01T00:00:00+00:00"
    assert state.artifacts.test_specs.digest == "spec-digest"
    assert state.artifacts.test_specs.produced_at == ""
    assert state.artifacts.implementation_plan.digest == "plan-digest"
    assert state.artifacts.implementation_plan.produced_at == ""
    assert state.test_spec_review.verdict == ""
    assert state.plan_review.verdict == ""
    assert state.dor is not None
    assert state.dor.status == "needs_work"
    assert state.grounding.valid is False
    assert state.build_review.verdict == ""
    assert state.finalize.status == "pending"
    assert state.build_start_base_sha == ""


def test_normalize_mark_phase_clears_legacy_overrides_but_keeps_canonical_phase() -> None:
    """mark-phase normalization rewrites the canonical phase and empties legacy override fields."""
    state = TodoState.defaults()
    state.prepare_phase = "requirements_review"
    state.work_phase = "build_started"

    normalize_mark_phase(state, LifecyclePhase.PLAN_REVIEW)

    assert state.lifecycle_phase == LifecyclePhase.PLAN_REVIEW.value
    assert state.prepare_phase == ""
    assert state.work_phase == ""
