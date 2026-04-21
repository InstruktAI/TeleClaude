# guard: no-companion
"""Regression tests for canonical lifecycle phase persistence."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.lifecycle import LifecyclePhase, advance_until_blocked, normalize_mark_phase
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_advance_until_blocked_keeps_incomplete_prepare_phase_stored() -> None:
    """The machine leaves the stored lifecycle phase in place until evidence completes it."""
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value

    phase = advance_until_blocked(state)

    assert phase == LifecyclePhase.REQUIREMENTS_REVIEW
    assert state.lifecycle_phase == LifecyclePhase.REQUIREMENTS_REVIEW.value


def test_normalize_mark_phase_clears_legacy_overrides_but_keeps_canonical_phase() -> None:
    """mark-phase normalization rewrites the canonical phase and empties legacy override fields."""
    state = TodoState.defaults()
    state.prepare_phase = "requirements_review"
    state.work_phase = "build_started"

    normalize_mark_phase(state, LifecyclePhase.PLAN_REVIEW)

    assert state.lifecycle_phase == LifecyclePhase.PLAN_REVIEW.value
    assert state.prepare_phase == ""
    assert state.work_phase == ""
