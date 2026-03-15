"""Characterization tests for teleclaude.cli.tui.widgets.todo_file_row."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow


@pytest.mark.unit
def test_todo_file_row_is_importable() -> None:
    assert TodoFileRow is not None


@pytest.mark.unit
def test_todo_file_row_stores_filepath_and_filename() -> None:
    row = TodoFileRow(filepath="/todos/my-todo/requirements.md", filename="requirements.md")
    assert row.filepath == "/todos/my-todo/requirements.md"
    assert row.filename == "requirements.md"


@pytest.mark.unit
def test_todo_file_row_default_slug_is_empty() -> None:
    row = TodoFileRow(filepath="/todos/roadmap.yaml", filename="roadmap.yaml")
    assert row.slug == ""


@pytest.mark.unit
def test_todo_file_row_default_is_last_is_false() -> None:
    row = TodoFileRow(filepath="/todos/roadmap.yaml", filename="roadmap.yaml")
    assert row.is_last is False


@pytest.mark.unit
def test_todo_file_row_default_tree_lines_is_empty() -> None:
    row = TodoFileRow(filepath="/todos/roadmap.yaml", filename="roadmap.yaml")
    assert row._tree_lines == []


@pytest.mark.unit
def test_todo_file_row_pressed_message_is_defined() -> None:
    assert TodoFileRow.Pressed is not None
