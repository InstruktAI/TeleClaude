"""Unit tests for mark-phase validation helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import validate_mark_phase_preconditions
from teleclaude.types.state_value import StateValue

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_STATE_IO = "teleclaude.core.next_machine.state_io"


def _prepared_state() -> dict[str, StateValue]:
    return {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {
            "requirements": {"produced_at": "2026-01-01T00:00:00+00:00"},
            "test_specs": {"produced_at": "2026-01-01T00:00:00+00:00"},
            "implementation_plan": {"produced_at": "2026-01-01T00:00:00+00:00"},
        },
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8, "status": "pass"},
        "grounding": {"valid": True},
        "lifecycle_phase": "prepared",
    }


def test_input_assessment_always_valid() -> None:
    assert validate_mark_phase_preconditions({}, "input_assessment", None) is None


def test_build_started_requires_prepared_prerequisites() -> None:
    result = validate_mark_phase_preconditions({}, "build_started", None)

    assert result is not None
    assert "prepared" in result


def test_build_started_accepts_prepared_state() -> None:
    result = validate_mark_phase_preconditions(_prepared_state(), "build_started", None)

    assert result is None


def test_build_complete_rejected_without_commits() -> None:
    with patch(f"{_STATE_IO}._has_build_commits_beyond_main", return_value=False):
        result = validate_mark_phase_preconditions(_prepared_state(), "build_complete", "/some/worktree")

    assert result is not None
    assert "commits beyond main" in result


def test_build_complete_accepted_with_commits() -> None:
    with patch(f"{_STATE_IO}._has_build_commits_beyond_main", return_value=True):
        result = validate_mark_phase_preconditions(_prepared_state(), "build_complete", "/some/worktree")

    assert result is None


def test_review_approved_requires_approve_verdict() -> None:
    state = _prepared_state() | {"build_review": {"verdict": "changes_requested"}}

    result = validate_mark_phase_preconditions(state, "review_approved", None)

    assert result is not None
    assert "approve" in result


def test_review_approved_accepts_approve_verdict() -> None:
    state = _prepared_state() | {"build_review": {"verdict": "approve"}}

    result = validate_mark_phase_preconditions(state, "review_approved", None)

    assert result is None


def test_finalize_ready_requires_ready_status() -> None:
    state = _prepared_state() | {"build_review": {"verdict": "approve"}}

    result = validate_mark_phase_preconditions(state, "finalize_ready", None)

    assert result is not None
    assert "finalize.status" in result


def test_finalize_ready_accepts_ready_status() -> None:
    state = _prepared_state() | {
        "build_review": {"verdict": "approve"},
        "finalize": {"status": "ready"},
    }

    result = validate_mark_phase_preconditions(state, "finalize_ready", None)

    assert result is None


def test_handed_off_requires_handed_off_status() -> None:
    state = _prepared_state() | {"finalize": {"status": "ready"}}

    result = validate_mark_phase_preconditions(state, "handed_off", None)

    assert result is not None
    assert "handed_off" in result
