"""Unit tests for phase_labels mapping functions."""

import pytest

from teleclaude.cli.tui.phase_labels import integration_phase_label, prepare_phase_label


# -- prepare_phase_label --


@pytest.mark.parametrize(
    "phase,expected_label",
    [
        ("input_assessment", "P:discovery"),
        ("triangulation", "P:discovery"),
        ("requirements_review", "P:requirements"),
        ("plan_drafting", "P:planning"),
        ("plan_review", "P:planning"),
        ("gate", "P:planning"),
        ("grounding_check", "P:planning"),
        ("re_grounding", "P:planning"),
    ],
)
def test_prepare_phase_label_active_phases(phase, expected_label):
    """Active prepare phases map to the correct display label."""
    result = prepare_phase_label(phase)
    assert result is not None
    label, color = result
    assert label == expected_label


def test_prepare_phase_label_discovery_color():
    """Discovery phases use cyan color."""
    _, color = prepare_phase_label("input_assessment")
    assert color == "cyan"


def test_prepare_phase_label_requirements_color():
    """Requirements phase uses cyan color."""
    _, color = prepare_phase_label("requirements_review")
    assert color == "cyan"


def test_prepare_phase_label_planning_color():
    """Planning phases use cyan color."""
    _, color = prepare_phase_label("plan_drafting")
    assert color == "cyan"


def test_prepare_phase_label_blocked():
    """Blocked phase maps to P:blocked with red color."""
    result = prepare_phase_label("blocked")
    assert result is not None
    label, color = result
    assert label == "P:blocked"
    assert color == "red"


def test_prepare_phase_label_prepared_returns_none():
    """prepared phase returns None (no P column)."""
    assert prepare_phase_label("prepared") is None


def test_prepare_phase_label_empty_string_returns_none():
    """Empty string returns None."""
    assert prepare_phase_label("") is None


def test_prepare_phase_label_none_returns_none():
    """None returns None."""
    assert prepare_phase_label(None) is None


def test_prepare_phase_label_unknown_returns_none():
    """Unknown phase values return None (defensive)."""
    assert prepare_phase_label("totally_unknown_phase") is None


# -- integration_phase_label --


@pytest.mark.parametrize(
    "phase,finalize_status,expected_label",
    [
        ("candidate_dequeued", None, "I:started"),
        ("clearance_wait", None, "I:started"),
        ("merge_clean", None, "I:started"),
        ("merge_conflicted", None, "I:started"),
        ("awaiting_commit", None, "I:started"),
        ("committed", None, "I:started"),
        ("delivery_bookkeeping", None, "I:started"),
        ("push_succeeded", None, "I:delivered"),
        ("cleanup", None, "I:delivered"),
        ("candidate_delivered", None, "I:delivered"),
        ("completed", None, "I:delivered"),
        ("push_rejected", None, "I:failed"),
    ],
)
def test_integration_phase_label_active_phases(phase, finalize_status, expected_label):
    """Active integration phases map to the correct display label."""
    result = integration_phase_label(phase, finalize_status)
    assert result is not None
    label, _ = result
    assert label == expected_label


def test_integration_phase_label_started_color():
    """Started phases use magenta color."""
    _, color = integration_phase_label("candidate_dequeued", None)
    assert color == "magenta"


def test_integration_phase_label_delivered_color():
    """Delivered phases use green color."""
    _, color = integration_phase_label("candidate_delivered", None)
    assert color == "green"


def test_integration_phase_label_failed_color():
    """Failed phase uses red color."""
    _, color = integration_phase_label("push_rejected", None)
    assert color == "red"


def test_integration_phase_label_queued_signal():
    """finalize_status=handed_off with no integration_phase returns I:queued."""
    result = integration_phase_label(None, "handed_off")
    assert result is not None
    label, color = result
    assert label == "I:queued"
    assert color == "magenta"


def test_integration_phase_label_both_none_returns_none():
    """Both phase and finalize_status None returns None."""
    assert integration_phase_label(None, None) is None


def test_integration_phase_label_finalize_pending_no_phase_returns_none():
    """finalize_status=pending with no integration_phase returns None."""
    assert integration_phase_label(None, "pending") is None


def test_integration_phase_label_empty_string_phase_returns_queued_if_handed_off():
    """Empty string phase with handed_off finalize_status returns I:queued."""
    result = integration_phase_label("", "handed_off")
    assert result is not None
    label, _ = result
    assert label == "I:queued"


def test_integration_phase_label_unknown_returns_none():
    """Unknown phase values return None (defensive)."""
    assert integration_phase_label("totally_unknown", None) is None
