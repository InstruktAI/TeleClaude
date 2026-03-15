"""Characterization tests for teleclaude.cli.tui.widgets.todo_row."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import (
    TodoRow,
    _pad,
    integration_phase_label,
    prepare_phase_label,
)
from teleclaude.core.integration.state_machine import IntegrationPhase
from teleclaude.core.next_machine.core import PreparePhase


def _make_todo(*, slug: str = "test-slug", status: TodoStatus = TodoStatus.PENDING) -> TodoItem:
    return TodoItem(
        slug=slug,
        status=status,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
    )


# --- prepare_phase_label ---


@pytest.mark.unit
def test_prepare_phase_label_returns_none_for_none_phase() -> None:
    assert prepare_phase_label(None) is None


@pytest.mark.unit
def test_prepare_phase_label_returns_none_for_unknown_phase() -> None:
    assert prepare_phase_label("bogus-phase") is None


@pytest.mark.unit
def test_prepare_phase_label_input_assessment_maps_to_discovery() -> None:
    result = prepare_phase_label(PreparePhase.INPUT_ASSESSMENT.value)
    assert result is not None
    prefix, value, _ = result
    assert prefix == "P"
    assert value == "discovery"


@pytest.mark.unit
def test_prepare_phase_label_blocked_returns_gold_color() -> None:
    result = prepare_phase_label(PreparePhase.BLOCKED.value)
    assert result is not None
    prefix, value, color = result
    assert prefix == "P"
    assert value == "blocked"
    assert str(color) == "color(136)"


@pytest.mark.unit
def test_prepare_phase_label_planning_phases_map_to_planning() -> None:
    for phase in (PreparePhase.PLAN_DRAFTING, PreparePhase.PLAN_REVIEW, PreparePhase.GATE):
        result = prepare_phase_label(phase.value)
        assert result is not None
        _, value, _ = result
        assert value == "planning"


# --- integration_phase_label ---


@pytest.mark.unit
def test_integration_phase_label_returns_none_for_none_phase_and_no_finalize() -> None:
    assert integration_phase_label(None, None) is None


@pytest.mark.unit
def test_integration_phase_label_started_for_candidate_dequeued() -> None:
    result = integration_phase_label(IntegrationPhase.CANDIDATE_DEQUEUED.value, None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "started"
    assert str(color) == "color(28)"


@pytest.mark.unit
def test_integration_phase_label_delivered_for_completed() -> None:
    result = integration_phase_label(IntegrationPhase.COMPLETED.value, None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "delivered"
    assert str(color) == "color(28)"


@pytest.mark.unit
def test_integration_phase_label_failed_for_push_rejected() -> None:
    result = integration_phase_label(IntegrationPhase.PUSH_REJECTED.value, None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "failed"
    assert str(color) == "color(136)"


@pytest.mark.unit
def test_integration_phase_label_queued_when_finalize_handed_off() -> None:
    result = integration_phase_label(None, "handed_off")
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "queued"
    assert str(color) == "color(28)"


# --- TodoRow.compute_col_widths ---


@pytest.mark.unit
def test_compute_col_widths_returns_zero_widths_for_empty_list() -> None:
    widths = TodoRow.compute_col_widths([])
    assert all(v == 0 for v in widths.values())


@pytest.mark.unit
def test_compute_col_widths_returns_non_zero_dor_width_when_dor_present() -> None:
    todo = _make_todo()
    todo = TodoItem(
        slug="test",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        dor_score=75,
    )
    widths = TodoRow.compute_col_widths([todo])
    assert widths["DOR"] > 0


@pytest.mark.unit
def test_compute_col_widths_returns_zero_for_absent_columns() -> None:
    todo = _make_todo()
    widths = TodoRow.compute_col_widths([todo])
    assert widths["B"] == 0
    assert widths["R"] == 0


@pytest.mark.unit
def test_compute_col_widths_includes_col_gap() -> None:
    from teleclaude.cli.tui.widgets.todo_row import _COL_GAP

    todo = TodoItem(
        slug="test",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        dor_score=100,
    )
    widths = TodoRow.compute_col_widths([todo])
    # DOR:100 has 7 chars; width should be 7 + _COL_GAP
    assert widths["DOR"] == len("DOR:100") + _COL_GAP


# --- _pad ---


@pytest.mark.unit
def test_pad_adds_dot_leaders_to_reach_target_width() -> None:
    from rich.text import Text

    t = Text("ab")
    result = _pad(t, 5)
    plain = result.plain
    assert plain.startswith("ab")
    assert len(plain) == 5


@pytest.mark.unit
def test_pad_does_not_shorten_text_wider_than_target() -> None:
    from rich.text import Text

    t = Text("abcdef")
    result = _pad(t, 3)
    assert len(result.plain) == 6  # unchanged
