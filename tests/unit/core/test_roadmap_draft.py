# guard: no-companion
"""Tests for roadmap projection of draft todos."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.roadmap import assemble_roadmap_from_db
from teleclaude.core.todos_db import TodosDb


@pytest.mark.asyncio
async def test_roadmap_projection_returns_pending_status_for_draft_todos(tmp_path: Path) -> None:
    """Draft todos must appear as status='pending' in the roadmap projection, not 'in_progress'."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("draft-item", description="A draft idea")
        await database.write_state(
            "draft-item",
            {"kind": "draft", "schema_version": 1, "phase": "pending"},
        )
        await database.write_artifact("draft-item", "input", "some content")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "draft-item"
    assert todos[0].status == "pending"
