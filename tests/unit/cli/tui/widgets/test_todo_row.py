"""Characterization tests for teleclaude.cli.tui.widgets.todo_row."""

# pylint: disable=import-outside-toplevel

from __future__ import annotations

import pytest

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import (
    TodoRow,
    _gold_color,
    _ok_color,
    _pad,
    _red_color,
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
def test_prepare_phase_label_blocked_returns_red_color() -> None:
    result = prepare_phase_label(PreparePhase.BLOCKED.value)
    assert result is not None
    prefix, value, color = result
    assert prefix == "P"
    assert value == "blocked"
    assert color == _red_color()


@pytest.mark.unit
def test_prepare_phase_label_test_spec_phases_map_to_requirements() -> None:
    for phase in (PreparePhase.TEST_SPEC_BUILD, PreparePhase.TEST_SPEC_REVIEW):
        result = prepare_phase_label(phase.value)
        assert result is not None
        _, value, _ = result
        assert value == "requirements"


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
    assert color == _ok_color()


@pytest.mark.unit
def test_integration_phase_label_delivered_for_completed() -> None:
    result = integration_phase_label(IntegrationPhase.COMPLETED.value, None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "delivered"
    assert color == _ok_color()


@pytest.mark.unit
def test_integration_phase_label_failed_for_push_rejected() -> None:
    result = integration_phase_label(IntegrationPhase.PUSH_REJECTED.value, None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "failed"
    assert color == _gold_color()


@pytest.mark.unit
def test_integration_phase_label_ready_when_finalize_ready() -> None:
    result = integration_phase_label(None, "ready")
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "ready"
    assert color == _ok_color()


@pytest.mark.unit
def test_integration_phase_label_queued_when_finalize_handed_off() -> None:
    result = integration_phase_label(None, "handed_off")
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "queued"
    assert color == _ok_color()


# --- TodoRow.compute_col_widths ---


@pytest.mark.unit
def test_compute_col_widths_returns_zero_widths_for_empty_list() -> None:
    widths = TodoRow.compute_col_widths([])
    assert all(v == 0 for k, v in widths.items() if k != "_max")


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


# --- Row width uniformity ---


@pytest.mark.unit
def test_all_rows_render_same_width_regardless_of_phase() -> None:
    """Every rendered row must have the same plain-text width when given shared col_widths.

    This covers: holder (no columns), prepare phase, integration phase, work phase (B/R),
    and bare (no phase, no DOR). All must pad to the same total width.
    """
    holder_child = TodoItem(
        slug="child-a",
        status=TodoStatus.DELIVERED,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        group="holder-parent",
    )
    holder = TodoItem(
        slug="holder-parent",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        children_statuses=["delivered"],
    )
    prepare_item = TodoItem(
        slug="prep-item",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=True,
        has_impl_plan=False,
        prepare_phase="input_assessment",
    )
    integration_item = TodoItem(
        slug="integ-item",
        status=TodoStatus.DELIVERED,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        integration_phase="candidate_delivered",
    )
    work_item = TodoItem(
        slug="work-item",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        build_status="complete",
        review_status="approved",
        dor_score=9,
    )
    bare_item = TodoItem(
        slug="bare-item",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
    )

    all_items = [holder, holder_child, prepare_item, integration_item, work_item, bare_item]
    slug_width = max(len(t.slug) for t in all_items)
    col_widths = TodoRow.compute_col_widths(all_items)

    rendered_widths: dict[str, int] = {}
    for item in all_items:
        row = TodoRow(
            todo=item,
            slug_width=slug_width,
            col_widths=col_widths,
            max_depth=0,
        )
        rendered = row.render()
        rendered_widths[item.slug] = len(rendered.plain)

    widths = list(rendered_widths.values())
    assert len(set(widths)) == 1, f"Row widths differ — all must be equal. Got: {rendered_widths}"
