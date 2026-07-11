"""Functional tests for the todo-row alignment contract."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional

TRA_SPEC = "project/spec/feature/tui/todo-row-alignment"


@pytest.mark.spec(TRA_SPEC, "UC-TRA1")
async def test_narrow_pane_keeps_shared_offset_and_intact_state_column(snapshot: object) -> None:
    # A long-slug sibling forces enough slug_width padding to engage the narrow
    # regime at a still-generous pane width (70 cells), and a nested held row
    # at a different tree depth proves the shared offset holds across depths.
    long_item = TodoItem(
        slug="a-very-long-slug-name-for-padding-purposes",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase="build_started",
    )
    held_item = TodoItem(
        slug="held",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase="build_started",
        hold=True,
        held=True,
    )
    items = [long_item, held_item]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    max_depth = 1

    class _AlignmentApp(App[None]):
        def compose(self) -> ComposeResult:
            yield TodoRow(
                long_item,
                is_last=False,
                slug_width=slug_width,
                col_widths=col_widths,
                tree_lines=[],
                max_depth=max_depth,
                id="long",
            )
            yield TodoRow(
                held_item,
                is_last=True,
                slug_width=slug_width,
                col_widths=col_widths,
                tree_lines=[False],
                max_depth=max_depth,
                id="held",
            )

    app = _AlignmentApp()
    async with app.run_test(size=(70, 6)) as pilot:
        await pilot.pause()
        rendered = [app.query_one(f"#{row_id}", TodoRow).render().plain for row_id in ("long", "held")]

    assert rendered == snapshot
