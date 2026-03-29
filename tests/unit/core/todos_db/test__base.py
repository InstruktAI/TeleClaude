"""RED tests for TodosDbBase — connection lifecycle and schema bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio


async def test_initialize_creates_database_file(tmp_path: Path) -> None:
    db_path = tmp_path / "sub" / "todos.db"
    db = TodosDb(str(db_path))
    await db.initialize()
    assert db_path.exists()
    await db.close()


async def test_initialize_creates_all_tables(todos_db: TodosDb) -> None:
    assert todos_db.conn is not None
    async with todos_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
    ) as cursor:
        rows = await cursor.fetchall()
    table_names = {row[0] for row in rows}
    assert table_names >= {"todo_state", "todo_artifacts", "todo_artifact_versions", "roadmap", "roadmap_deps"}


async def test_close_sets_conn_to_none(tmp_path: Path) -> None:
    db = TodosDb(str(tmp_path / "todos.db"))
    await db.initialize()
    await db.close()
    assert db.conn is None
