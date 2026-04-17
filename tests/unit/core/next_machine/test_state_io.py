"""Unit tests for state_io validation helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import validate_work_phase_preconditions

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_PHASE_DERIVATION = "teleclaude.core.next_machine.phase_derivation"


def test_build_started_always_valid() -> None:
    """build_started has no preconditions — always returns None."""
    assert validate_work_phase_preconditions({}, "build_started", None) is None


def test_build_complete_rejected_without_commits() -> None:
    """build_complete requires commits beyond main."""
    with patch(f"{_PHASE_DERIVATION}._has_build_commits_beyond_main", return_value=False):
        result = validate_work_phase_preconditions({}, "build_complete", "/some/worktree")

    assert result is not None
    assert "commits beyond main" in result


def test_build_complete_accepted_with_commits() -> None:
    """build_complete passes when commits exist."""
    with patch(f"{_PHASE_DERIVATION}._has_build_commits_beyond_main", return_value=True):
        result = validate_work_phase_preconditions({}, "build_complete", "/some/worktree")

    assert result is None


def test_build_complete_skips_check_without_worktree() -> None:
    """build_complete passes when no worktree_cwd is provided (pre-worktree setup)."""
    result = validate_work_phase_preconditions({}, "build_complete", None)
    assert result is None


def test_finalize_ready_rejected_without_approve_verdict() -> None:
    """finalize_ready requires build_review.verdict == 'approve'."""
    state: dict = {"build_review": {"verdict": "changes_requested"}}
    result = validate_work_phase_preconditions(state, "finalize_ready", None)
    assert result is not None
    assert "approve" in result


def test_finalize_ready_accepted_with_approve_verdict() -> None:
    """finalize_ready passes when verdict is approve."""
    state: dict = {"build_review": {"verdict": "approve"}}
    result = validate_work_phase_preconditions(state, "finalize_ready", None)
    assert result is None


def test_review_approved_rejected_without_verdict() -> None:
    """review_approved requires a build_review.verdict to be set."""
    result = validate_work_phase_preconditions({}, "review_approved", None)
    assert result is not None
    assert "verdict" in result


def test_review_approved_accepted_with_verdict() -> None:
    """review_approved passes when any verdict is set."""
    state: dict = {"build_review": {"verdict": "approve"}}
    result = validate_work_phase_preconditions(state, "review_approved", None)
    assert result is None


def test_handed_off_rejected_without_finalize_ready() -> None:
    """handed_off requires finalize.status == 'ready'."""
    result = validate_work_phase_preconditions({}, "handed_off", None)
    assert result is not None
    assert "finalize" in result.lower()
