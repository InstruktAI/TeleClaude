"""Functional tests for todo row rendering."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional


def test_kindless_todo_row_renders_unknown_kind_and_classify_phase(snapshot: object) -> None:
    item = TodoItem(
        slug="classify-me",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind=None,
        lifecycle_phase=None,
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot
