"""Characterization tests for teleclaude/cli/editor.py."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# EditorApp class attributes — no instantiation needed
# ---------------------------------------------------------------------------


def test_editor_app_language_map_maps_py_to_python() -> None:
    from teleclaude.cli.editor import EditorApp

    assert EditorApp._LANGUAGE_MAP[".py"] == "python"


def test_editor_app_language_map_maps_yaml_extensions() -> None:
    from teleclaude.cli.editor import EditorApp

    assert EditorApp._LANGUAGE_MAP[".yaml"] == "yaml"
    assert EditorApp._LANGUAGE_MAP[".yml"] == "yaml"


def test_editor_app_language_map_maps_json() -> None:
    from teleclaude.cli.editor import EditorApp

    assert EditorApp._LANGUAGE_MAP[".json"] == "json"


def test_editor_app_language_map_maps_toml() -> None:
    from teleclaude.cli.editor import EditorApp

    assert EditorApp._LANGUAGE_MAP[".toml"] == "toml"


def test_editor_app_language_map_maps_md_to_markdown() -> None:
    from teleclaude.cli.editor import EditorApp

    assert EditorApp._LANGUAGE_MAP[".md"] == "markdown"


def test_editor_app_markdown_exts_includes_md() -> None:
    from teleclaude.cli.editor import EditorApp

    assert ".md" in EditorApp._MARKDOWN_EXTS


def test_editor_app_markdown_exts_includes_txt() -> None:
    from teleclaude.cli.editor import EditorApp

    assert ".txt" in EditorApp._MARKDOWN_EXTS


# ---------------------------------------------------------------------------
# EditorApp.__init__ — file existence check
# ---------------------------------------------------------------------------


def test_editor_app_raises_file_not_found_for_missing_file(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    missing = tmp_path / "nonexistent.md"
    with pytest.raises(FileNotFoundError):
        EditorApp(file_path=missing)


def test_editor_app_stores_file_path_and_view_mode(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    test_file = tmp_path / "test.md"
    test_file.write_text("# Hello\n")
    app = EditorApp(file_path=test_file, view_mode=True)
    assert app.file_path == test_file
    assert app.view_mode is True


def test_editor_app_view_mode_defaults_to_false(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    test_file = tmp_path / "test.md"
    test_file.write_text("# Hello\n")
    app = EditorApp(file_path=test_file)
    assert app.view_mode is False


# ---------------------------------------------------------------------------
# EditorApp._save_if_changed — saves only when content differs
# ---------------------------------------------------------------------------


def test_save_if_changed_skips_save_when_content_unchanged(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    test_file = tmp_path / "test.md"
    test_file.write_text("original content")
    app = EditorApp(file_path=test_file)
    # _last_saved_content is None until compose() is called
    # Manually set to simulate post-compose state
    app._last_saved_content = "original content"
    app._save_if_changed("original content")
    # Content unchanged — file should not be rewritten
    assert test_file.read_text() == "original content"


def test_save_if_changed_saves_when_content_differs(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    test_file = tmp_path / "test.md"
    test_file.write_text("original content")
    app = EditorApp(file_path=test_file)
    app._last_saved_content = "original content"
    app._save_if_changed("new content")
    assert test_file.read_text() == "new content"
