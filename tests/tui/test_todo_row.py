"""Functional tests for todo row rendering."""

from __future__ import annotations

import pytest

import teleclaude.cli.tui.widgets.todo_row as todo_row_mod
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional


def test_kindless_todo_row_renders_question_mark_kind_and_classify_phase(snapshot: object) -> None:
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


def test_todo_row_renders_compact_kind_labels(snapshot: object) -> None:
    items = [
        TodoItem(
            slug="my-feature",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="feature",
            lifecycle_phase=None,
        ),
        TodoItem(
            slug="my-change",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="change",
            lifecycle_phase=None,
        ),
        TodoItem(
            slug="my-bug",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="bug",
            lifecycle_phase=None,
        ),
        TodoItem(
            slug="my-task",
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind="task",
            lifecycle_phase=None,
        ),
    ]
    slug_width = max(len(i.slug) for i in items)
    col_widths = TodoRow.compute_col_widths(items)
    rows = [TodoRow(item, slug_width=slug_width, col_widths=col_widths) for item in items]

    assert [r.render().plain for r in rows] == snapshot


def test_todo_row_renders_disapproved_review_status(snapshot: object) -> None:
    item = TodoItem(
        slug="fix-review",
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="change",
        lifecycle_phase="review_changes_requested",
    )
    row = TodoRow(
        item,
        slug_width=len(item.slug),
        col_widths=TodoRow.compute_col_widths([item]),
    )

    assert row.render().plain == snapshot


def test_todo_row_kind_column_color_per_kind_in_dark_and_light_mode(
    monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    """Kind column applies distinct per-kind colors in dark and light mode."""
    kinds: list[str | None] = ["feature", "change", "bug", "task", None]
    results: list[tuple[str, str, str | None]] = []

    slug_names = ["alpha", "bravo", "charlie", "delta", "echo"]
    for kind, slug in zip(kinds, slug_names):
        item = TodoItem(
            slug=slug,
            status=TodoStatus.IN_PROGRESS,
            description=None,
            has_requirements=False,
            has_impl_plan=False,
            kind=kind,
            lifecycle_phase=None,
        )
        row = TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))
        kind_display = todo_row_mod._display_kind(kind)

        for mode, is_dark in [("dark", True), ("light", False)]:
            monkeypatch.setattr(todo_row_mod, "is_dark_mode", lambda _d=is_dark: _d)
            rendered = row.render()
            kind_pos = rendered.plain.index(kind_display)
            kind_color: str | None = None
            for span in rendered._spans:
                if span.start == kind_pos and span.end == kind_pos + len(kind_display):
                    if hasattr(span.style, "color") and span.style.color:
                        kind_color = span.style.color.name
                        break
            results.append((kind or "kindless", mode, kind_color))

    assert results == snapshot
