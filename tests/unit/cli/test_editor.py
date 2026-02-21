"""Tests for the standalone markdown editor app."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_editor_module_is_importable() -> None:
    """Editor module can be imported without side effects."""
    from teleclaude.cli.editor import EditorApp

    assert EditorApp is not None


def test_editor_app_creates_with_file_path(tmp_path: Path) -> None:
    """EditorApp accepts a file path and stores it."""
    test_file = tmp_path / "test.md"
    test_file.write_text("# Hello\n")

    from teleclaude.cli.editor import EditorApp

    app = EditorApp(file_path=test_file)
    assert app.file_path == test_file


def test_editor_app_rejects_missing_file() -> None:
    """EditorApp raises if file does not exist."""
    from teleclaude.cli.editor import EditorApp

    with pytest.raises(FileNotFoundError):
        EditorApp(file_path=Path("/nonexistent/file.md"))


def test_editor_save_writes_content(tmp_path: Path) -> None:
    """_save() writes TextArea content back to the file."""
    test_file = tmp_path / "test.md"
    test_file.write_text("original content")

    from teleclaude.cli.editor import EditorApp

    app = EditorApp(file_path=test_file)
    # Simulate what _save does with a known string
    app._save_content("new content")
    assert test_file.read_text() == "new content"
