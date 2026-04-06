"""Behavioral coverage for teleclaude.cli.editor."""
# pylint: disable=import-outside-toplevel,missing-function-docstring,protected-access

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

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


def test_materialized_artifact_from_db_preserves_logical_artifact_name(tmp_path: Path) -> None:
    from teleclaude.cli.editor import MaterializedArtifact

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


def test_render_view_prints_header_and_content(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from teleclaude.cli.editor import _render_view

    target = tmp_path / "input"
    target.write_text("line 1\nline 2\n", encoding="utf-8")

    _render_view(target, "input")

    output = capsys.readouterr().out
    assert "[VIEW] input" in output
    assert "line 1" in output
    assert "line 2" in output


def test_persist_if_changed_skips_identical_content(tmp_path: Path) -> None:
    from teleclaude.cli.editor import persist_if_changed

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
    from teleclaude.cli.editor import persist_if_changed

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
    from teleclaude.cli.editor import EditorApp

    target = tmp_path / "artifact"
    target.write_text("before\n", encoding="utf-8")
    app = EditorApp(target)

    async with app.run_test() as pilot:
        await pilot.press("x", "enter", "y", "escape")

    assert target.read_text(encoding="utf-8") == "x\nybefore\n"


def test_main_view_mode_prints_artifact_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from teleclaude.cli import editor

    project_root, _db = _seed_artifact_project(tmp_path, artifact_name="input", content="hello\n")
    monkeypatch.setattr(editor, "_wait_until_terminated", lambda: None)
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
            "input",
            "--view",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        editor.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "[VIEW] input" in output
    assert "hello" in output


def test_main_edit_mode_persists_artifact_back_to_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from teleclaude.cli import editor

    project_root, db = _seed_artifact_project(tmp_path, artifact_name="requirements", content="before\n")

    def _fake_inline_editor(
        file_path: Path,
        display_name: str,
        *,
        save_callback: Callable[[str], None] | None = None,
    ) -> int:
        assert display_name == "requirements"
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
