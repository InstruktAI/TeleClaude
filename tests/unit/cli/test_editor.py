"""Behavioral coverage for teleclaude.cli.editor."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.widgets import Markdown, TextArea

from teleclaude.cli import editor
from teleclaude.cli.editor import EditorApp, MaterializedArtifact, persist_if_changed
from teleclaude.core.todos_db import TodosDb


def _seed_artifact_project(
    tmp_path: Path,
    *,
    slug: str = "todo-1",
    artifact_name: str = "requirements",
    content: str = "# Hello\n",
) -> tuple[Path, TodosDb]:
    project_root = tmp_path / "project"
    db = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
    db.initialize_sync()
    row_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = db._sync_conn()
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


def test_materialized_artifact_from_db_preserves_logical_artifact_name(tmp_path: Path) -> None:
    project_root, _db = _seed_artifact_project(tmp_path)
    materialized = MaterializedArtifact.from_db(
        project_root=project_root,
        slug="todo-1",
        artifact_name="requirements",
    )
    try:
        assert materialized.display_name == "requirements"
        assert materialized.file_path.name == "requirements"
        assert materialized.file_path.read_text(encoding="utf-8") == "# Hello\n"
    finally:
        materialized.cleanup()


@pytest.mark.unit
async def test_editor_app_view_mode_renders_markdown_and_uses_requested_theme(tmp_path: Path) -> None:
    target = tmp_path / "input"
    target.write_text("# Heading\n", encoding="utf-8")
    app = EditorApp(target, view_mode=True, theme_name="teleclaude-light-agent")

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "teleclaude-light-agent"
        assert len(app.query(Markdown)) == 1
        assert len(app.query(TextArea)) == 0


@pytest.mark.unit
async def test_editor_app_edit_mode_renders_markdown_text_area(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    target.write_text("# Heading\n", encoding="utf-8")
    app = EditorApp(target, theme_name="teleclaude-dark-agent")

    async with app.run_test() as pilot:
        await pilot.pause()
        editor = app.query_one("#editor-area", TextArea)
        assert editor.language == "markdown"
        assert app.theme == "teleclaude-dark-agent"


def test_persist_if_changed_skips_identical_content(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    target.write_text("same\n", encoding="utf-8")
    saved: list[str] = []
    changed = persist_if_changed(
        target,
        "same\n",
        last_saved_content="same\n",
        save_callback=saved.append,
    )

    assert changed is False
    assert target.read_text(encoding="utf-8") == "same\n"
    assert not saved


def test_persist_if_changed_writes_and_calls_callback(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    target.write_text("before\n", encoding="utf-8")
    saved: list[str] = []
    changed = persist_if_changed(
        target,
        "after\n",
        last_saved_content="before\n",
        save_callback=saved.append,
    )

    assert changed is True
    assert target.read_text(encoding="utf-8") == "after\n"
    assert saved == ["after\n"]


@pytest.mark.timeout(60)
async def test_editor_app_enter_and_escape_persist_multiline_buffer(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    target.write_text("before\n", encoding="utf-8")
    app = EditorApp(target)

    async with app.run_test() as pilot:
        await pilot.press("x", "enter", "y", "escape")

    assert target.read_text(encoding="utf-8") == "x\nybefore\n"


def test_main_view_mode_launches_themed_markdown_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _db = _seed_artifact_project(tmp_path, artifact_name="input", content="hello\n")
    calls: list[tuple[Path, str, bool, str, object]] = []

    def _fake_inline_editor(
        file_path: Path,
        display_name: str,
        *,
        view_mode: bool = False,
        theme_name: str = "teleclaude-dark",
        save_callback: object = None,
    ) -> int:
        calls.append((file_path, display_name, view_mode, theme_name, save_callback))
        return 0

    monkeypatch.setattr(editor, "_run_inline_editor", _fake_inline_editor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "teleclaude.cli.editor",
            "--theme",
            "teleclaude-light-agent",
            "--project-root",
            str(project_root),
            "--artifact-slug",
            "todo-1",
            "--artifact-name",
            "input",
            "--view",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        editor.main()

    assert exc_info.value.code == 0
    assert len(calls) == 1
    _file_path, display_name, view_mode, theme_name, save_callback = calls[0]
    assert display_name == "input"
    assert view_mode is True
    assert theme_name == "teleclaude-light-agent"
    assert save_callback is None


def test_main_edit_mode_persists_artifact_back_to_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, db = _seed_artifact_project(tmp_path, artifact_name="requirements", content="before\n")

    def _fake_inline_editor(
        file_path: Path,
        display_name: str,
        *,
        view_mode: bool = False,
        theme_name: str = "teleclaude-dark",
        save_callback: Callable[[str], None] | None = None,
    ) -> int:
        assert display_name == "requirements"
        assert view_mode is False
        assert theme_name == "teleclaude-dark"
        file_path.write_text("after\n", encoding="utf-8")
        assert save_callback is not None
        save_callback("after\n")
        return 0

    monkeypatch.setattr(editor, "_run_inline_editor", _fake_inline_editor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "teleclaude.cli.editor",
            "--project-root",
            str(project_root),
            "--artifact-slug",
            "todo-1",
            "--artifact-name",
            "requirements",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        editor.main()

    assert exc_info.value.code == 0
    assert db.read_artifact_sync("todo-1", "requirements") == "after\n"
