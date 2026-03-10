"""Unit tests for phase label mapping functions."""

from unittest.mock import patch

import pytest

from teleclaude.cli.tui.widgets.todo_row import integration_phase_label, prepare_phase_label


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
@pytest.mark.parametrize(
    "phase,expected_label",
    [
        ("input_assessment", ("P", "discovery")),
        ("triangulation", ("P", "discovery")),
        ("requirements_review", ("P", "requirements")),
        ("plan_drafting", ("P", "planning")),
        ("plan_review", ("P", "planning")),
        ("gate", ("P", "planning")),
        ("grounding_check", ("P", "planning")),
        ("re_grounding", ("P", "planning")),
    ],
)
def test_prepare_phase_label_active_phases(_mock, phase, expected_label):
    """Active prepare phases map to the expected split label/value tuple."""
    result = prepare_phase_label(phase)
    assert result is not None
    prefix, value, _ = result
    assert (prefix, value) == expected_label


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_prepare_phase_label_discovery_color(_mock):
    """Discovery phases use the ok color in dark mode."""
    _, _, color = prepare_phase_label("input_assessment")
    assert color == "color(71)"


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_prepare_phase_label_requirements_color(_mock):
    """Requirements phase uses the ok color in dark mode."""
    _, _, color = prepare_phase_label("requirements_review")
    assert color == "color(71)"


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_prepare_phase_label_planning_color(_mock):
    """Planning phases use the ok color in dark mode."""
    _, _, color = prepare_phase_label("plan_drafting")
    assert color == "color(71)"


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_prepare_phase_label_blocked(_mock):
    """Blocked maps to a split P:blocked label and failed/orange color."""
    result = prepare_phase_label("blocked")
    assert result is not None
    prefix, value, color = result
    assert (prefix, value) == ("P", "blocked")
    assert color == "color(178)"


def test_prepare_phase_label_prepared_returns_none():
    """prepared phase returns None (no P column)."""
    assert prepare_phase_label("prepared") is None


def test_prepare_phase_label_empty_string_returns_none():
    """Empty string returns None."""
    assert prepare_phase_label("") is None


def test_prepare_phase_label_none_returns_none():
    """None phase returns None."""
    assert prepare_phase_label(None) is None


def test_prepare_phase_label_unknown_returns_none():
    """Unknown phase values return None defensively."""
    assert prepare_phase_label("totally_unknown_phase") is None


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
@pytest.mark.parametrize(
    "phase,finalize_status,expected_label",
    [
        ("candidate_dequeued", None, ("I", "started")),
        ("clearance_wait", None, ("I", "started")),
        ("merge_clean", None, ("I", "started")),
        ("merge_conflicted", None, ("I", "started")),
        ("awaiting_commit", None, ("I", "started")),
        ("committed", None, ("I", "started")),
        ("delivery_bookkeeping", None, ("I", "started")),
        ("push_succeeded", None, ("I", "delivered")),
        ("cleanup", None, ("I", "delivered")),
        ("candidate_delivered", None, ("I", "delivered")),
        ("completed", None, ("I", "delivered")),
        ("push_rejected", None, ("I", "failed")),
    ],
)
def test_integration_phase_label_active_phases(_mock, phase, finalize_status, expected_label):
    """Integration/queued phases map to the expected split label/value tuple."""
    result = integration_phase_label(phase, finalize_status)
    assert result is not None
    prefix, value, _ = result
    assert (prefix, value) == expected_label


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_integration_phase_label_started_color(_mock):
    """Started phases use the ok color in dark mode."""
    _, _, color = integration_phase_label("candidate_dequeued", None)
    assert color == "color(71)"


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_integration_phase_label_delivered_color(_mock):
    """Delivered phases use the ok color in dark mode."""
    _, _, color = integration_phase_label("candidate_delivered", None)
    assert color == "color(71)"


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_integration_phase_label_failed_color(_mock):
    """Failed phase uses the gold color in dark mode."""
    _, _, color = integration_phase_label("push_rejected", None)
    assert color == "color(178)"


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_integration_phase_label_queued_signal(_mock):
    """handoff queue signal renders I:queued."""
    result = integration_phase_label(None, "handed_off")
    assert result is not None
    prefix, value, color = result
    assert (prefix, value) == ("I", "queued")
    assert color == "color(71)"


def test_integration_phase_label_both_none_returns_none():
    """Both phase and finalize_status None returns None."""
    assert integration_phase_label(None, None) is None


def test_integration_phase_label_finalize_pending_no_phase_returns_none():
    """finalize_status=pending with no phase returns None."""
    assert integration_phase_label(None, "pending") is None


@patch("teleclaude.cli.tui.widgets.todo_row.is_dark_mode", return_value=True)
def test_integration_phase_label_empty_string_phase_returns_queued_if_handed_off(_mock):
    """Empty string phase with handed_off finalize_status returns I:queued."""
    result = integration_phase_label("", "handed_off")
    assert result is not None
    prefix, value, _ = result
    assert (prefix, value) == ("I", "queued")


def test_integration_phase_label_unknown_returns_none():
    """Unknown phase values return None defensively."""
    assert integration_phase_label("totally_unknown", None) is None
