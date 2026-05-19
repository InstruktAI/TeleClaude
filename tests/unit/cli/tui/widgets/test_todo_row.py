"""Characterization tests for teleclaude.cli.tui.widgets.todo_row."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.geometry import Size

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import (
    _COL_GAP,
    _WIDGET_PADDING_HORZ,
    TodoRow,
    _muted_color,
    _ok_color,
    _pad,
    integration_phase_label,
    lifecycle_phase_label,
    row_content_width,
)
from teleclaude.core.next_machine.lifecycle import LifecyclePhase


def _make_todo(*, slug: str = "test-slug", status: TodoStatus = TodoStatus.PENDING) -> TodoItem:
    return TodoItem(
        slug=slug,
        status=status,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
    )


# --- lifecycle_phase_label ---


@pytest.mark.unit
def test_prepare_phase_label_returns_none_for_none_phase() -> None:
    assert lifecycle_phase_label(None) is None


@pytest.mark.unit
def test_prepare_phase_label_returns_none_for_unknown_phase() -> None:
    assert lifecycle_phase_label("bogus-phase") is None


@pytest.mark.unit
def test_lifecycle_phase_label_prd_drafting_maps_to_prd_drafting() -> None:
    result = lifecycle_phase_label(LifecyclePhase.PRD_DRAFTING.value)
    assert result is not None
    prefix, value, _ = result
    assert prefix == "P"
    assert value == "PRD drafting"


@pytest.mark.unit
def test_lifecycle_phase_label_prd_human_approval_maps_to_prd_approval() -> None:
    """PRD_HUMAN_APPROVAL is distinct from PRD_DRAFTING — no longer collapsed."""
    result = lifecycle_phase_label(LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    assert result is not None
    prefix, value, _ = result
    assert prefix == "P"
    assert value == "PRD approval"


@pytest.mark.unit
def test_lifecycle_phase_label_draft_maps_to_intake() -> None:
    result = lifecycle_phase_label(LifecyclePhase.DRAFT.value)
    assert result is not None
    prefix, value, _ = result
    assert prefix == "P"
    assert value == "intake"


@pytest.mark.unit
def test_lifecycle_phase_label_test_specs_drafting_maps_to_specs_drafting() -> None:
    result = lifecycle_phase_label(LifecyclePhase.TEST_SPECS_DRAFTING.value)
    assert result is not None
    _, value, _ = result
    assert value == "specs drafting"


@pytest.mark.unit
def test_lifecycle_phase_label_test_specs_review_maps_to_specs_review() -> None:
    result = lifecycle_phase_label(LifecyclePhase.TEST_SPECS_REVIEW.value)
    assert result is not None
    _, value, _ = result
    assert value == "specs review"


@pytest.mark.unit
def test_lifecycle_phase_label_plan_drafting_maps_to_plan_drafting() -> None:
    result = lifecycle_phase_label(LifecyclePhase.PLAN_DRAFTING.value)
    assert result is not None
    _, value, _ = result
    assert value == "plan drafting"


@pytest.mark.unit
def test_lifecycle_phase_label_plan_review_maps_to_plan_review() -> None:
    result = lifecycle_phase_label(LifecyclePhase.PLAN_REVIEW.value)
    assert result is not None
    _, value, _ = result
    assert value == "plan review"


# --- integration_phase_label ---


@pytest.mark.unit
def test_integration_phase_label_returns_none_for_none_phase_and_no_finalize() -> None:
    assert integration_phase_label(None, None) is None


@pytest.mark.unit
def test_integration_phase_label_started() -> None:
    result = integration_phase_label("started", None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "started"
    assert color == _ok_color()


@pytest.mark.unit
def test_integration_phase_label_delivered() -> None:
    result = integration_phase_label("delivered", None)
    assert result is not None
    prefix, value, color = result
    assert prefix == "I"
    assert value == "delivered"
    assert color == _muted_color()


@pytest.mark.unit
def test_integration_phase_label_unknown_value_returns_none() -> None:
    """Legacy/stale phase values produce no label — roadmap.py handles mapping."""
    assert integration_phase_label("delivery_bookkeeping", None) is None


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
def test_compute_col_widths_uses_phase_column_for_prepare_lane() -> None:
    todo = TodoItem(
        slug="test",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        lifecycle_phase="prepared",
    )
    widths = TodoRow.compute_col_widths([todo])
    assert widths["P"] > 0


@pytest.mark.unit
def test_compute_col_widths_returns_zero_for_absent_columns() -> None:
    todo = _make_todo()
    widths = TodoRow.compute_col_widths([todo])
    assert widths["B"] == 0
    assert widths["R"] == 0


@pytest.mark.unit
def test_compute_col_widths_includes_col_gap() -> None:
    todo = TodoItem(
        slug="test",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        lifecycle_phase="prepared",
    )
    widths = TodoRow.compute_col_widths([todo])
    assert widths["P"] == len("P:prepared") + _COL_GAP


# --- _pad ---


@pytest.mark.unit
def test_pad_adds_dot_leaders_to_reach_target_width() -> None:
    t = Text("ab")
    result = _pad(t, 5)
    plain = result.plain
    assert plain.startswith("ab")
    assert len(plain) == 5


@pytest.mark.unit
def test_pad_does_not_shorten_text_wider_than_target() -> None:
    t = Text("abcdef")
    result = _pad(t, 3)
    assert len(result.plain) == 6  # unchanged


# --- Row width uniformity ---


@pytest.mark.unit
def test_all_rows_render_same_width_regardless_of_phase() -> None:
    """Every rendered row must have the same plain-text width when given shared col_widths.

    This covers: holder (no columns), prepare phase, integration phase, work phase (B/R),
    and bare (no phase/work columns). All must pad to the same total width.
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
        status=TodoStatus.DELIVERED,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        is_holder=True,
    )
    prepare_item = TodoItem(
        slug="prep-item",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=True,
        has_impl_plan=False,
        lifecycle_phase="prd_drafting",
    )
    integration_item = TodoItem(
        slug="integ-item",
        status=TodoStatus.DELIVERED,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        integration_phase="delivered",
    )
    work_item = TodoItem(
        slug="work-item",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        lifecycle_phase="review_approved",
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


# --- row_content_width ---


@pytest.mark.unit
def test_row_content_width_is_shared_formula() -> None:
    """row_content_width exposes the canonical content width for all prep rows."""
    # Formula: 8 fixed overhead + slug_width + max_depth * 2 + col_width
    assert row_content_width(slug_width=0, max_depth=0, col_width=0) == 8
    assert row_content_width(slug_width=5, max_depth=0, col_width=1) == 14
    assert row_content_width(slug_width=10, max_depth=2, col_width=15) == 37


@pytest.mark.unit
def test_row_content_width_matches_render_output() -> None:
    """row_content_width must predict the actual rendered width (no size constraint)."""
    todo = _make_todo(slug="my-slug")
    all_items = [todo]
    slug_width = max(len(t.slug) for t in all_items)
    col_widths = TodoRow.compute_col_widths(all_items)
    col_width = col_widths.get("_max", 0)

    row = TodoRow(todo=todo, slug_width=slug_width, col_widths=col_widths, max_depth=0)
    rendered_width = len(row.render().plain)

    assert rendered_width == row_content_width(slug_width=slug_width, max_depth=0, col_width=col_width)


# --- graceful degradation ---


@pytest.mark.unit
def test_render_shrinks_dot_leaders_in_narrow_pane() -> None:
    """When outer_size is narrower than the natural content width, dot leaders are reduced."""
    todo = _make_todo(slug="short")
    col_widths = TodoRow.compute_col_widths([todo])
    # row_content_width(5, 0, 1) == 14; pane outer_size=15 → content_area=13
    # prefix(6) + slug(5) + col(1) = 12; max_dots = 13 - 12 = 1 (down from 2)

    row_normal = TodoRow(todo=todo, slug_width=5, col_widths=col_widths, max_depth=0)
    normal_width = len(row_normal.render().plain)

    row_narrow = TodoRow(todo=todo, slug_width=5, col_widths=col_widths, max_depth=0)
    row_narrow._size = Size(15, 1)
    narrow_width = len(row_narrow.render().plain)

    assert narrow_width < normal_width, f"Narrow pane must reduce dot leaders: {narrow_width} >= {normal_width}"
    assert narrow_width <= 13, f"Must fit in content area (15 - 2 = 13): got {narrow_width}"


@pytest.mark.unit
def test_render_eliminates_dots_when_very_narrow() -> None:
    """When pane is so narrow dot leaders cannot fit, the rendered row fits the content area."""
    todo = _make_todo(slug="short")
    col_widths = TodoRow.compute_col_widths([todo])
    # outer_size=12 → content_area=10; max_dots=max(0, 10-6-5-1)=0 (eliminated)
    # Full row with cols (12 chars) is truncated to content_area.
    row = TodoRow(todo=todo, slug_width=5, col_widths=col_widths, max_depth=0)
    row._size = Size(12, 1)
    rendered = row.render()
    content_area = 12 - _WIDGET_PADDING_HORZ  # = 10
    assert len(rendered.plain) <= content_area


@pytest.mark.unit
def test_render_work_row_does_not_include_prepare_phase_column() -> None:
    work_item = TodoItem(
        slug="work-item",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        lifecycle_phase="review_approved",
    )
    col_widths = TodoRow.compute_col_widths([work_item])
    row = TodoRow(todo=work_item, slug_width=len(work_item.slug), col_widths=col_widths, max_depth=0)

    rendered = row.render().plain

    assert "B:complete" in rendered
    assert "R:approved" in rendered
    assert "P:" not in rendered
