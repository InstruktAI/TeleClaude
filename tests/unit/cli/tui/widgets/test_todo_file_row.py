"""Characterization tests for teleclaude.cli.tui.widgets.todo_file_row."""

# pylint: disable=protected-access

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow


@pytest.mark.unit
def test_todo_file_row_is_importable() -> None:
    assert TodoFileRow is not None


@pytest.mark.unit
def test_todo_file_row_stores_artifact_key_and_filename() -> None:
    row = TodoFileRow(artifact_key="requirements", filename="requirements.md")
    assert row.artifact_key == "requirements"
    assert row.filename == "requirements.md"


@pytest.mark.unit
def test_todo_file_row_default_slug_is_empty() -> None:
    row = TodoFileRow(artifact_key="roadmap", filename="roadmap.yaml")
    assert row.slug == ""


@pytest.mark.unit
def test_todo_file_row_default_is_last_is_false() -> None:
    row = TodoFileRow(artifact_key="roadmap", filename="roadmap.yaml")
    assert row.is_last is False


@pytest.mark.unit
def test_todo_file_row_default_tree_lines_is_empty() -> None:
    row = TodoFileRow(artifact_key="roadmap", filename="roadmap.yaml")
    assert row._tree_lines == []


@pytest.mark.unit
def test_todo_file_row_pressed_message_is_defined() -> None:
    assert TodoFileRow.Pressed is not None
