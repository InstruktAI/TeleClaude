"""Functional tests for the todos.db schema migrations.

Covers the roadmap->todo substrate rename: the physical table rename, child
foreign-key cascade retargeting, the partial-unique index, and the legacy
markdown importer landing rows in the renamed ``todo`` table.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._base import _bootstrap_todos_db, _table_exists

pytestmark = pytest.mark.functional

_SLUG = "alpha"
_DEP = "beta"
_ROW_ID = "id-1"
_VERSION_ID_COL = "version_id"


def _build_pre_rename_schema(db_path: Path) -> None:
    """Create a todos.db at the pre-rename schema (table ``roadmap`` + children)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE roadmap ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
            "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
            "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "removed_at TEXT, prev_status TEXT, removed_deps TEXT, pending_purge_paths TEXT)"
        )
        conn.execute(
            "CREATE TABLE roadmap_deps (slug TEXT NOT NULL, depends_on TEXT NOT NULL, PRIMARY KEY (slug, depends_on))"
        )
        conn.execute(
            "CREATE TABLE todo_state ("
            "id TEXT PRIMARY KEY REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE todo_artifacts ("
            "id TEXT NOT NULL REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '', "
            "updated_by TEXT, updated_at TEXT, PRIMARY KEY (id, name))"
        )
        conn.execute(
            "CREATE TABLE todo_artifact_versions ("
            "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "id TEXT NOT NULL REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_roadmap_slug_active ON roadmap(slug) WHERE status IN ('active', 'icebox')"
        )
        conn.execute(
            "INSERT INTO roadmap (id, slug, status, created_at, updated_at) "
            "VALUES ('id-1', 'alpha', 'active', 'now', 'now')"
        )
        conn.execute("INSERT INTO roadmap_deps (slug, depends_on) VALUES ('alpha', 'beta')")
        conn.execute(
            "INSERT INTO todo_state (id, slug, state, created_at, updated_at) "
            "VALUES ('id-1', 'alpha', '{}', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO todo_artifacts (id, slug, name, content, digest) "
            "VALUES ('id-1', 'alpha', 'input', 'body', 'd')"
        )
        conn.execute(
            "INSERT INTO todo_artifact_versions (id, slug, name, content, digest, created_at) "
            "VALUES ('id-1', 'alpha', 'input', 'body', 'd', 'now')"
        )
        conn.commit()
    finally:
        conn.close()


def test_roadmap_substrate_renamed_to_todo(tmp_path: Path) -> None:
    """The migration renames roadmap->todo and roadmap_deps->todo_deps."""
    db_path = tmp_path / "todos.db"
    _build_pre_rename_schema(db_path)

    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        assert _table_exists(conn, "todo")
        assert _table_exists(conn, "todo_deps")
        assert not _table_exists(conn, "roadmap")
        assert not _table_exists(conn, "roadmap_deps")
        # Data survived the rename.
        assert conn.execute("SELECT slug FROM todo").fetchone()[0] == _SLUG
        assert conn.execute("SELECT depends_on FROM todo_deps").fetchone()[0] == _DEP
    finally:
        conn.close()


def test_child_foreign_keys_cascade_from_todo(tmp_path: Path) -> None:
    """Deleting a todo row cascades to its state/artifact/version children."""
    db_path = tmp_path / "todos.db"
    _build_pre_rename_schema(db_path)

    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM todo WHERE id = 'id-1'")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM todo_state").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM todo_artifacts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM todo_artifact_versions").fetchone()[0] == 0
    finally:
        conn.close()


def test_partial_unique_index_on_todo_slug(tmp_path: Path) -> None:
    """idx_todo_slug_active forbids two active rows with the same slug."""
    db_path = tmp_path / "todos.db"
    _build_pre_rename_schema(db_path)

    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO todo (id, slug, status, created_at, updated_at) "
                "VALUES ('id-2', 'alpha', 'active', 'now', 'now')"
            )
        # A delivered duplicate is allowed (outside the partial predicate).
        conn.execute(
            "INSERT INTO todo (id, slug, status, created_at, updated_at) "
            "VALUES ('id-3', 'alpha', 'delivered', 'now', 'now')"
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_is_idempotent_on_already_renamed_db(tmp_path: Path) -> None:
    """Re-bootstrapping a renamed DB is a guarded no-op."""
    db_path = tmp_path / "todos.db"
    _build_pre_rename_schema(db_path)

    _bootstrap_todos_db(str(db_path))
    # Second run must not raise and must leave the renamed substrate intact.
    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        assert _table_exists(conn, "todo")
        assert not _table_exists(conn, "roadmap")
    finally:
        conn.close()


def test_legacy_markdown_import_lands_in_todo_table(tmp_path: Path) -> None:
    """The legacy roadmap.md importer writes entries into the renamed todo table."""
    project_root = tmp_path / "project"
    teleclaude_dir = project_root / ".teleclaude"
    todos_dir = project_root / "todos"
    teleclaude_dir.mkdir(parents=True)
    todos_dir.mkdir(parents=True)
    (todos_dir / "roadmap.md").write_text(f"- [ ] {_SLUG} - first task\n", encoding="utf-8")

    db_path = teleclaude_dir / "todos.db"
    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        assert _table_exists(conn, "todo")
        slugs = [row[0] for row in conn.execute("SELECT slug FROM todo")]
        assert _SLUG in slugs
    finally:
        conn.close()


def test_migration_survives_missing_child_table(tmp_path: Path) -> None:
    """A partial legacy DB with `roadmap` but a missing child table migrates without crashing."""
    db_path = tmp_path / "todos.db"
    conn = sqlite3.connect(db_path)
    try:
        # Only the parent and deps exist; child tables are absent.
        conn.execute(
            "CREATE TABLE roadmap ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
            "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
            "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "removed_at TEXT, prev_status TEXT, removed_deps TEXT, pending_purge_paths TEXT)"
        )
        conn.execute(
            "CREATE TABLE roadmap_deps (slug TEXT NOT NULL, depends_on TEXT NOT NULL, PRIMARY KEY (slug, depends_on))"
        )
        conn.execute(
            "INSERT INTO roadmap (id, slug, status, created_at, updated_at) "
            "VALUES ('id-1', 'alpha', 'active', 'now', 'now')"
        )
        conn.commit()
    finally:
        conn.close()

    # Must not raise; create_all builds the absent child tables against the renamed parent.
    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        assert _table_exists(conn, "todo")
        assert not _table_exists(conn, "roadmap")
        assert _table_exists(conn, "todo_state")
        assert _table_exists(conn, "todo_artifacts")
        assert _table_exists(conn, "todo_artifact_versions")
        assert conn.execute("SELECT slug FROM todo").fetchone()[0] == _SLUG
    finally:
        conn.close()


def test_bootstrap_strips_holder_state_and_preserves_artifacts(tmp_path: Path) -> None:
    """Legacy bootstrap strips a holder's todo_state but preserves its non-input artifacts and versions."""
    db_path = tmp_path / "todos.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE roadmap ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
            "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
            "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "removed_at TEXT, prev_status TEXT, removed_deps TEXT, pending_purge_paths TEXT)"
        )
        conn.execute(
            "CREATE TABLE roadmap_deps (slug TEXT NOT NULL, depends_on TEXT NOT NULL, PRIMARY KEY (slug, depends_on))"
        )
        conn.execute(
            "CREATE TABLE todo_state ("
            "id TEXT PRIMARY KEY REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE todo_artifacts ("
            "id TEXT NOT NULL REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '', "
            "updated_by TEXT, updated_at TEXT, PRIMARY KEY (id, name))"
        )
        conn.execute(
            "CREATE TABLE todo_artifact_versions ("
            "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "id TEXT NOT NULL REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_roadmap_slug_active ON roadmap(slug) WHERE status IN ('active', 'icebox')"
        )
        # Parent (about to become a holder) plus a grouped child.
        conn.execute(
            "INSERT INTO roadmap (id, slug, status, created_at, updated_at) "
            "VALUES ('parent-1', 'parent', 'active', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO roadmap (id, slug, group_slug, status, created_at, updated_at) "
            "VALUES ('child-1', 'child', 'parent', 'active', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO todo_state (id, slug, state, created_at, updated_at) "
            "VALUES ('parent-1', 'parent', '{}', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO todo_artifacts (id, slug, name, content, digest) "
            "VALUES ('parent-1', 'parent', 'implementation-plan', 'plan body', 'd')"
        )
        conn.execute(
            "INSERT INTO todo_artifact_versions (id, slug, name, content, digest, created_at) "
            "VALUES ('parent-1', 'parent', 'implementation-plan', 'plan body', 'd', 'now')"
        )
        conn.commit()
    finally:
        conn.close()

    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM todo_state WHERE id = 'parent-1'").fetchone()[0] == 0
        artifact = conn.execute(
            "SELECT content FROM todo_artifacts WHERE id = 'parent-1' AND name = 'implementation-plan'"
        ).fetchone()
        assert artifact is not None and artifact[0] == "plan body"
        version = conn.execute(
            "SELECT content FROM todo_artifact_versions WHERE id = 'parent-1' AND name = 'implementation-plan'"
        ).fetchone()
        assert version is not None and version[0] == "plan body"
    finally:
        conn.close()


def test_artifact_version_schema_fix_keeps_owner_id_on_renamed_db(tmp_path: Path) -> None:
    """On an already-renamed `todo` DB, the old artifact-version schema fix keeps real owner ids."""
    db_path = tmp_path / "todos.db"
    conn = sqlite3.connect(db_path)
    try:
        # Already-renamed parent table; no legacy `roadmap`.
        conn.execute(
            "CREATE TABLE todo ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
            "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
            "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "removed_at TEXT, prev_status TEXT, removed_deps TEXT, pending_purge_paths TEXT)"
        )
        conn.execute(
            "INSERT INTO todo (id, slug, status, created_at, updated_at) "
            "VALUES ('id-1', 'alpha', 'active', 'now', 'now')"
        )
        # Old artifact-version schema: `id INTEGER` version counter, no `version_id`,
        # owner resolved by slug.
        conn.execute(
            "CREATE TABLE todo_artifact_versions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO todo_artifact_versions (slug, name, content, digest, updated_by, created_at) "
            "VALUES ('alpha', 'input', 'body', 'd', 'x', 'now')"
        )
        conn.commit()
    finally:
        conn.close()

    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(todo_artifact_versions)")}
        assert _VERSION_ID_COL in columns
        # Owner id resolved from the renamed `todo` table, not a fresh UUID.
        owner_id = conn.execute("SELECT id FROM todo_artifact_versions WHERE slug = ?", (_SLUG,)).fetchone()[0]
        assert owner_id == _ROW_ID
    finally:
        conn.close()


_LEGACY_PRINCIPAL = "human:legacy@example.com"
_CREATED_BY_AGENT_COL = "created_by_agent"


async def test_created_by_agent_migrates_additively_on_old_shape_row(tmp_path: Path) -> None:
    """A pre-`created_by_agent` `todo` row migrates additively with no data loss."""
    db_path = tmp_path / "todos.db"
    conn = sqlite3.connect(db_path)
    try:
        # Already-renamed parent table that has `created_by_principal` but
        # predates `created_by_agent`.
        conn.execute(
            "CREATE TABLE todo ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
            "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
            "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "removed_at TEXT, prev_status TEXT, removed_deps TEXT, pending_purge_paths TEXT, "
            "created_by_principal TEXT)"
        )
        conn.execute(
            "INSERT INTO todo (id, slug, status, created_at, updated_at, created_by_principal) "
            "VALUES (?, ?, 'active', 'now', 'now', ?)",
            (_ROW_ID, _SLUG, _LEGACY_PRINCIPAL),
        )
        conn.commit()
    finally:
        conn.close()

    _bootstrap_todos_db(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(todo)")}
        assert _CREATED_BY_AGENT_COL in columns
        # The pre-existing row survives with its principal intact and the new
        # column reading back None.
        row = conn.execute(
            "SELECT created_by_principal, created_by_agent FROM todo WHERE id = ?", (_ROW_ID,)
        ).fetchone()
        assert row == (_LEGACY_PRINCIPAL, None)
    finally:
        conn.close()

    # The read path surfaces None for the legacy row without error.
    todos_db = TodosDb(str(db_path))
    try:
        await todos_db.initialize()
        assert await todos_db.read_created_by_agent(_SLUG) is None
        assert await todos_db.read_created_by_principal(_SLUG) == _LEGACY_PRINCIPAL
    finally:
        await todos_db.close()
