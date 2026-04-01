"""RED tests for TodosDbBase — connection lifecycle and schema bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from teleclaude.core.todos_db import TodosDb


def _old_artifact_versions_schema_ddl() -> str:
    """Return the old DDL for todo_artifact_versions (id INTEGER PRIMARY KEY, no version_id)."""
    return (
        "CREATE TABLE todo_artifact_versions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "slug TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL, "
        "digest TEXT NOT NULL, updated_by TEXT, created_at TEXT NOT NULL)"
    )


def _artifact_versions_col_types(db_path: str) -> dict[str, str]:
    """Return a mapping of column name → declared type for todo_artifact_versions."""
    conn = sqlite3.connect(db_path)
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(todo_artifact_versions)").fetchall()}
    conn.close()
    return cols


async def test_initialize_creates_database_file(tmp_path: Path) -> None:
    """initialize() must create the database file and any missing parent directories."""
    db_path = tmp_path / "sub" / "todos.db"
    db = TodosDb(str(db_path))
    await db.initialize()
    assert db_path.exists()
    await db.close()


async def test_initialize_creates_all_tables(todos_db: TodosDb) -> None:
    """initialize() must bootstrap all required tables."""
    assert todos_db.conn is not None
    async with todos_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
    ) as cursor:
        rows = await cursor.fetchall()
    table_names = {row[0] for row in rows}
    assert table_names >= {"todo_state", "todo_artifacts", "todo_artifact_versions", "roadmap", "roadmap_deps"}


async def test_close_sets_conn_to_none(tmp_path: Path) -> None:
    """close() must set conn to None."""
    db = TodosDb(str(tmp_path / "todos.db"))
    await db.initialize()
    await db.close()
    assert db.conn is None


def test_initialize_sync_fixes_artifact_versions_when_uuid_migration_ran_but_left_integer_id(
    tmp_path: Path,
) -> None:
    """Databases where UUID migration ran but todo_artifact_versions kept id INTEGER PRIMARY KEY
    must be corrected to version_id INTEGER PK + id TEXT NOT NULL on next initialize."""
    db_path = str(tmp_path / "todos.db")

    # Simulate the broken post-migration state:
    # - roadmap already has id TEXT (UUID migration ran)
    # - todo_artifact_versions still has id INTEGER PRIMARY KEY (migration was wrongly skipped)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE roadmap (id TEXT PRIMARY KEY, slug TEXT NOT NULL, "
        "position INTEGER NOT NULL, group_slug TEXT, description TEXT, "
        "status TEXT NOT NULL DEFAULT 'active', delivered_at TEXT, "
        "delivered_commit TEXT, children TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(_old_artifact_versions_schema_ddl())
    conn.commit()
    conn.close()

    TodosDb(db_path).initialize_sync()

    cols = _artifact_versions_col_types(db_path)
    assert "version_id" in cols, "version_id column missing — schema not fixed"
    assert cols.get("id", "").upper() == "TEXT", "id column must be TEXT after fix"


def test_migrate_to_uuid_schema_fixes_artifact_versions_with_integer_id_primary_key(
    tmp_path: Path,
) -> None:
    """During UUID migration, todo_artifact_versions with id INTEGER PRIMARY KEY must be
    migrated to version_id INTEGER PK + id TEXT NOT NULL (not skipped)."""
    db_path = str(tmp_path / "todos.db")

    # Simulate pre-UUID state: roadmap WITHOUT id column + old artifact_versions schema
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE roadmap (slug TEXT PRIMARY KEY, position INTEGER NOT NULL, "
        "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE todo_state ("
        "slug TEXT PRIMARY KEY, state TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE todo_artifacts ("
        "slug TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', "
        "digest TEXT NOT NULL DEFAULT '', updated_by TEXT, updated_at TEXT, "
        "PRIMARY KEY (slug, name))"
    )
    conn.execute(_old_artifact_versions_schema_ddl())
    conn.commit()
    conn.close()

    TodosDb(db_path).initialize_sync()

    cols = _artifact_versions_col_types(db_path)
    assert "version_id" in cols, "version_id column missing after UUID migration"
    assert cols.get("id", "").upper() == "TEXT", "id column must be TEXT after UUID migration"
