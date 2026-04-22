"""Tests for legacy markdown todo auto-import during TodosDb bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from teleclaude.core.todos_db import TodosDb


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _roadmap_statuses(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT slug, status FROM roadmap").fetchall()  # guard: raw-sql
    finally:
        conn.close()
    return {str(slug): str(status) for slug, status in rows}


def _scaffold_legacy_markdown_todos(project_root: Path) -> None:
    todos_dir = project_root / "todos"
    _write(
        todos_dir / "roadmap.md",
        """# Roadmap

## Items

- [ ] alpha - Active alpha todo.
""",
    )
    _write(
        todos_dir / "icebox.md",
        """# Icebox

## Items

- [ ] beta - Iceboxed beta todo.
""",
    )
    _write(
        todos_dir / "delivered.md",
        """2026-01-01 | gamma | Delivered gamma todo | DELIVERED | abc123 | done/001-gamma
""",
    )
    _write(
        todos_dir / "bugs.md",
        """# Bugs

## Open Bugs

- [ ] **Example Broken Flow** - Active bug that should become a bug todo.

## Resolved Bugs

- [x] **Resolved Wrong Id** - Fixed bug that should become delivered.
""",
    )
    _write(todos_dir / "alpha" / "requirements.md", "# Alpha requirements\n")
    _write(todos_dir / "alpha" / "implementation-plan.md", "# Alpha plan\n")
    _write(todos_dir / "beta" / "requirements.md", "# Beta requirements\n")


async def test_initialize_auto_imports_legacy_markdown_todos_into_empty_db(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    db_path = project_root / ".teleclaude" / "todos.db"
    _scaffold_legacy_markdown_todos(project_root)

    db = TodosDb(str(db_path))
    await db.initialize()
    try:
        statuses = _roadmap_statuses(db_path)
        assert statuses == {
            "alpha": "active",
            "beta": "icebox",
            "gamma": "delivered",
            "fix-example-broken-flow": "active",
            "fix-resolved-wrong-id": "delivered",
        }
        assert await db.read_artifact("alpha", "requirements") == "# Alpha requirements\n"
        assert await db.read_artifact("alpha", "implementation-plan") == "# Alpha plan\n"
        bug_state = await db.read_state("fix-example-broken-flow")
        assert bug_state is not None
        assert bug_state["kind"] == "bug"
        assert await db.read_state("gamma") is None
    finally:
        await db.close()


def test_initialize_sync_auto_imports_legacy_markdown_todos_into_empty_db(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    db_path = project_root / ".teleclaude" / "todos.db"
    _scaffold_legacy_markdown_todos(project_root)

    db = TodosDb(str(db_path))
    db.initialize_sync()

    statuses = _roadmap_statuses(db_path)
    assert statuses == {
        "alpha": "active",
        "beta": "icebox",
        "gamma": "delivered",
        "fix-example-broken-flow": "active",
        "fix-resolved-wrong-id": "delivered",
    }
    assert db.read_artifact_sync("alpha", "requirements") == "# Alpha requirements\n"


async def test_initialize_skips_auto_import_when_db_already_has_todo_data(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    db_path = project_root / ".teleclaude" / "todos.db"

    db = TodosDb(str(db_path))
    await db.initialize()
    try:
        await db.add_to_roadmap("existing")
        await db.write_state(
            "existing", {"phase": "pending", "schema_version": 1, "lifecycle_phase": "input_assessment"}
        )
    finally:
        await db.close()

    _scaffold_legacy_markdown_todos(project_root)

    db = TodosDb(str(db_path))
    await db.initialize()
    try:
        statuses = _roadmap_statuses(db_path)
        assert statuses == {"existing": "active"}
        assert await db.read_artifact("existing", "requirements") == ""
    finally:
        await db.close()
