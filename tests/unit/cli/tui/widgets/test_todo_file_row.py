"""Characterization tests for teleclaude.cli.tui.widgets.todo_file_row."""

# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow


@pytest.mark.unit
def test_todo_file_row_is_importable() -> None:
    assert TodoFileRow is not None


@pytest.mark.unit
def test_todo_file_row_stores_artifact_name_and_filename() -> None:
    row = TodoFileRow(
        artifact_name="requirements",
        filename="requirements",
        slug="todo-1",
        project_path="/tmp/project",
    )
    assert row.artifact_name == "requirements"
    assert row.filename == "requirements"
    assert row.project_path == "/tmp/project"


@pytest.mark.unit
def test_todo_file_row_stores_slug() -> None:
    row = TodoFileRow(
        artifact_name="roadmap",
        filename="roadmap.yaml",
        slug="todo-1",
        project_path="/tmp/project",
    )
    assert row.slug == "todo-1"


@pytest.mark.unit
def test_todo_file_row_default_is_last_is_false() -> None:
    row = TodoFileRow(
        artifact_name="roadmap",
        filename="roadmap.yaml",
        slug="todo-1",
        project_path="/tmp/project",
    )
    assert row.is_last is False


@pytest.mark.unit
def test_todo_file_row_default_tree_lines_is_empty() -> None:
    row = TodoFileRow(
        artifact_name="roadmap",
        filename="roadmap.yaml",
        slug="todo-1",
        project_path="/tmp/project",
    )
    assert row._tree_lines == []


@pytest.mark.unit
def test_todo_file_row_pressed_message_is_defined() -> None:
    assert TodoFileRow.Pressed is not None
