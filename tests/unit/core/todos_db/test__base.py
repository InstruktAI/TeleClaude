"""Tests for TodosDbBase — connection lifecycle and schema bootstrap."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path

from teleclaude.core.todos_db import TodosDb

_SLUG = "phase-hook-slug"
_PRIOR_PHASE = "review_approved"
_NEW_PHASE = "finalize_ready"


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


async def test_initialize_sync_leaves_async_runtime_usable(tmp_path: Path) -> None:
    """A sync-init instance must remain usable from async callers.

    The factory caches one TodosDb per project path. If sync-first callers
    leave the async runtime unset, the cached instance breaks downstream
    async users. ``initialize_sync`` therefore sets up both runtimes.
    """
    db_path = tmp_path / "todos.db"
    db = TodosDb(str(db_path))
    db.initialize_sync()
    # Observable: the async session can be opened without raising
    # "TodosDb not initialized".
    async with db._session():
        pass
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


def test_notify_phase_transition_default_is_noop(tmp_path: Path) -> None:
    db = TodosDb(str(tmp_path / "todos.db"))

    db.notify_phase_transition(_SLUG, _PRIOR_PHASE, _NEW_PHASE, {})


def test_notify_phase_transition_invokes_installed_callback(tmp_path: Path) -> None:
    db = TodosDb(str(tmp_path / "todos.db"))
    state = {"lifecycle_phase": _NEW_PHASE}
    calls: list[tuple[str, str, str, Mapping[str, object]]] = []

    db._on_phase_transition = lambda slug, prior, new, payload: calls.append((slug, prior, new, payload))

    db.notify_phase_transition(_SLUG, _PRIOR_PHASE, _NEW_PHASE, state)

    assert calls == [(_SLUG, _PRIOR_PHASE, _NEW_PHASE, state)]


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


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def test_uuid_migration_assigns_uuid_to_artifacts_without_roadmap_entry(
    tmp_path: Path,
) -> None:
    """Artifacts whose slug has no roadmap entry must get a generated UUID as id,
    not the slug string."""
    db_path = str(tmp_path / "todos.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE roadmap (slug TEXT PRIMARY KEY, position INTEGER NOT NULL, "
        "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO roadmap VALUES ('known-slug', 0, NULL, NULL, 'active', NULL, NULL, NULL, "
        "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "CREATE TABLE todo_artifacts (slug TEXT NOT NULL, name TEXT NOT NULL, "
        "content TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '', "
        "updated_by TEXT, updated_at TEXT, PRIMARY KEY (slug, name))"
    )
    conn.execute("INSERT INTO todo_artifacts VALUES ('orphan-slug', 'input', 'content', 'digest', NULL, NULL)")
    conn.commit()
    conn.close()

    TodosDb(db_path).initialize_sync()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id FROM todo_artifacts WHERE slug = 'orphan-slug'").fetchone()
    conn.close()

    assert row is not None, "orphan artifact row should survive migration"
    assert _is_uuid(row[0]), f"artifact id must be a UUID, got {row[0]!r}"


def test_initialize_adds_roadmap_tombstone_and_pending_purge_columns_to_preexisting_db(tmp_path: Path) -> None:
    """A pre-existing roadmap table without tombstone columns must gain them additively,
    preserving existing rows."""
    db_path = str(tmp_path / "todos.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE roadmap (id TEXT PRIMARY KEY, slug TEXT NOT NULL, "
        "position INTEGER NOT NULL, group_slug TEXT, description TEXT, "
        "status TEXT NOT NULL DEFAULT 'active', delivered_at TEXT, "
        "delivered_commit TEXT, children TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO roadmap (id, slug, position, status, created_at, updated_at) "
        "VALUES ('row-1', 'kept-slug', 0, 'active', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    TodosDb(db_path).initialize_sync()
    TodosDb(db_path).initialize_sync()

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(roadmap)").fetchall()}
        preserved = conn.execute(
            "SELECT slug, status, removed_at, prev_status, removed_deps, pending_purge_paths "
            "FROM roadmap WHERE id = 'row-1'"
        ).fetchone()
    finally:
        conn.close()

    assert {"removed_at", "prev_status", "removed_deps", "pending_purge_paths"} <= columns
    assert preserved == ("kept-slug", "active", None, None, None, None)
