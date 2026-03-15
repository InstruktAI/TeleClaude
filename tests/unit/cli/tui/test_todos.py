from __future__ import annotations

import pytest

from teleclaude.cli.tui.todos import TodoItem, TodoStatus


@pytest.mark.unit
def test_todo_item_uses_fresh_default_lists_and_none_status_fields() -> None:
    first = TodoItem(
        slug="first",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=False,
    )
    second = TodoItem(
        slug="second",
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=False,
    )

    assert first.files == []
    assert first.after == []
    assert first.findings_count == 0
    assert first.build_status is None
    assert first.group is None
    assert first.files is not second.files
    assert first.after is not second.after
