"""Regression tests for TodoRow bug artifact styling."""

from __future__ import annotations

from rich.console import Console

from teleclaude.cli.tui.todos import TodoItem, TodoStatus
from teleclaude.cli.tui.widgets.todo_row import TodoRow


def test_bug_row_slug_is_not_dimmed_when_requirements_plan_are_missing() -> None:
    console = Console(width=120, force_terminal=False)

    bug_row = TodoRow(
        todo=TodoItem(
            slug="fix-login-bug",
            status=TodoStatus.PENDING,
            description="bug",
            has_requirements=False,
            has_impl_plan=False,
            dor_score=None,
            files=["bug.md"],
        )
    )
    feature_row = TodoRow(
        todo=TodoItem(
            slug="feature-work",
            status=TodoStatus.PENDING,
            description="feature",
            has_requirements=False,
            has_impl_plan=False,
            dor_score=None,
            files=["input.md"],
        )
    )

    bug_text = bug_row.render()
    bug_offset = bug_text.plain.index("fix-login-bug")
    bug_style = bug_text.get_style_at_offset(console, bug_offset)

    feature_text = feature_row.render()
    feature_offset = feature_text.plain.index("feature-work")
    feature_style = feature_text.get_style_at_offset(console, feature_offset)

    assert bug_style.color is None
    assert feature_style.color is not None
