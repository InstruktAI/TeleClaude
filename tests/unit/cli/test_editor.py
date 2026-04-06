"""Characterization tests for teleclaude/cli/editor.py."""
# pylint: disable=duplicate-code,import-outside-toplevel,missing-function-docstring,protected-access

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.widgets import Markdown, TextArea

from teleclaude.core.todos_db import TodosDb

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


def _seed_artifact_project(
    tmp_path: Path,
    *,
    slug: str = "todo-1",
    artifact_name: str = "requirements",
    content: str = "# Hello\n",
) -> tuple[Path, TodosDb]:
    """Create a temporary project with a populated todos.db artifact."""
    project_root = tmp_path / "project"
    db = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
    db.initialize_sync()
    now = datetime.now(UTC).isoformat()
    row_id = str(uuid.uuid4())
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        conn.execute(
            "INSERT INTO roadmap "  # guard: raw-sql
            "(id, slug, position, group_slug, description, status, delivered_at, "
            "delivered_commit, children, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, slug, 0, None, None, "active", None, None, None, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    db.write_artifact_sync(slug, artifact_name, content)
    return project_root, db


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


def test_materialized_artifact_from_db_uses_temp_markdown_file(tmp_path: Path) -> None:
    from teleclaude.cli.editor import MaterializedArtifact

    project_root, _db = _seed_artifact_project(tmp_path)
    materialized = MaterializedArtifact.from_db(
        project_root=project_root,
        slug="todo-1",
        artifact_name="requirements",
    )
    try:
        assert materialized.display_name == "requirements.md"
        assert materialized.file_path.name == "requirements.md"
        assert materialized.file_path.read_text(encoding="utf-8") == "# Hello\n"
    finally:
        materialized.cleanup()


@pytest.mark.unit
async def test_editor_app_view_mode_renders_markdown_preview(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    test_file = tmp_path / "test.md"
    test_file.write_text("# Heading\n")
    app = EditorApp(file_path=test_file, view_mode=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.query(Markdown)) == 1
        assert len(app.query(TextArea)) == 0


@pytest.mark.unit
async def test_editor_app_edit_mode_renders_text_area_and_save_persists_content(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp

    test_file = tmp_path / "test.md"
    test_file.write_text("original content")
    app = EditorApp(file_path=test_file)

    async with app.run_test() as pilot:
        await pilot.pause()
        editor = app.query_one("#editor-area", TextArea)
        editor.text = "updated content"
        app.action_save()
        await pilot.pause()

    assert test_file.read_text() == "updated content"


@pytest.mark.unit
async def test_editor_app_save_callback_persists_artifact_back_to_db(tmp_path: Path) -> None:
    from teleclaude.cli.editor import EditorApp, MaterializedArtifact

    project_root, db = _seed_artifact_project(tmp_path)
    materialized = MaterializedArtifact.from_db(
        project_root=project_root,
        slug="todo-1",
        artifact_name="requirements",
    )
    app = EditorApp(
        file_path=materialized.file_path,
        display_name=materialized.display_name,
        save_callback=materialized.persist,
    )

    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            editor = app.query_one("#editor-area", TextArea)
            editor.text = "updated artifact content"
            app.action_save()
            await pilot.pause()

        assert db.read_artifact_sync("todo-1", "requirements") == "updated artifact content"
    finally:
        materialized.cleanup()
