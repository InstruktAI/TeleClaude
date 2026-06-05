"""TodosDb base: connection lifecycle, schema bootstrap, and migrations."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session as SqlSession
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.db.connection_factory import create_async_db_engine, create_sync_db_engine

from ._legacy_import import maybe_auto_import_legacy_markdown_todos
from ._models import TODOS_DB_TABLES

logger = get_logger(__name__)


def _generate_id() -> str:
    """Generate a UUID for use as a todo identifier."""
    return str(uuid.uuid4())


def _default_on_mutation(_event_hint: str, _event_data: Mapping[str, object] | None = None) -> None:
    """Default no-op mutation callback."""


def _default_on_phase_transition(
    _slug: str,
    _prior_lifecycle_phase: str,
    _new_lifecycle_phase: str,
    _state_payload: Mapping[str, object],
) -> None:
    """Default no-op phase transition callback."""


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a table exists."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return column names for an existing table without SQLite schema pragmas."""
    if not _table_exists(conn, table_name):
        return set()
    cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT 0")  # guard: raw-sql
    return {column[0] for column in cursor.description or []}


def _table_sql(conn: sqlite3.Connection, table_name: str) -> str:
    """Return the CREATE TABLE SQL for a table, or an empty string if missing."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row[0]) if row and row[0] else ""


def _migrate_to_uuid_schema(conn: sqlite3.Connection) -> None:
    """Migrate from slug-as-PK to id-as-PK schema if needed."""
    roadmap_columns = _table_columns(conn, "roadmap")
    if "id" in roadmap_columns:
        return

    logger.info("Migrating todos.db to UUID-based schema")

    conn.execute(
        "CREATE TABLE roadmap_new ("
        "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
        "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    for row in conn.execute(
        "SELECT slug, group_slug, description, status, delivered_at, delivered_commit, children, created_at, updated_at "
        "FROM roadmap"
    ).fetchall():
        new_id = _generate_id()
        conn.execute(
            "INSERT INTO roadmap_new VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, row[0], None, *row[1:]),
        )
    conn.execute("DROP TABLE roadmap")
    conn.execute("ALTER TABLE roadmap_new RENAME TO roadmap")

    slug_to_id: dict[str, str] = {}
    for row_id, slug, status in conn.execute("SELECT id, slug, status FROM roadmap").fetchall():
        if status != "delivered" or slug not in slug_to_id:
            slug_to_id[str(slug)] = str(row_id)

    if _table_exists(conn, "todo_state"):
        conn.execute(
            "CREATE TABLE todo_state_new ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        for slug, state, created_at, updated_at in conn.execute(
            "SELECT slug, state, created_at, updated_at FROM todo_state"
        ).fetchall():
            row_id = slug_to_id.get(str(slug), _generate_id())
            conn.execute(
                "INSERT OR IGNORE INTO todo_state_new VALUES (?, ?, ?, ?, ?)",
                (row_id, slug, state, created_at, updated_at),
            )
        conn.execute("DROP TABLE todo_state")
        conn.execute("ALTER TABLE todo_state_new RENAME TO todo_state")

    if _table_exists(conn, "todo_artifacts"):
        conn.execute(
            "CREATE TABLE todo_artifacts_new ("
            "id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '', "
            "updated_by TEXT, updated_at TEXT, PRIMARY KEY (id, name))"
        )
        for slug, name, content, digest, updated_by, updated_at in conn.execute(
            "SELECT slug, name, content, digest, updated_by, updated_at FROM todo_artifacts"
        ).fetchall():
            row_id = slug_to_id.get(str(slug), _generate_id())
            conn.execute(
                "INSERT OR IGNORE INTO todo_artifacts_new VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, slug, name, content, digest, updated_by, updated_at),
            )
        conn.execute("DROP TABLE todo_artifacts")
        conn.execute("ALTER TABLE todo_artifacts_new RENAME TO todo_artifacts")

    if _table_exists(conn, "todo_artifact_versions"):
        version_columns = _table_columns(conn, "todo_artifact_versions")
        if "version_id" not in version_columns:
            conn.execute(
                "CREATE TABLE todo_artifact_versions_new ("
                "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, "
                "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
                "created_at TEXT NOT NULL)"
            )
            for slug, name, content, digest, updated_by, created_at in conn.execute(
                "SELECT slug, name, content, digest, updated_by, created_at FROM todo_artifact_versions"
            ).fetchall():
                row_id = slug_to_id.get(str(slug), _generate_id())
                conn.execute(
                    "INSERT INTO todo_artifact_versions_new "
                    "(id, slug, name, content, digest, updated_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (row_id, slug, name, content, digest, updated_by, created_at),
                )
            conn.execute("DROP TABLE todo_artifact_versions")
            conn.execute("ALTER TABLE todo_artifact_versions_new RENAME TO todo_artifact_versions")

    conn.commit()
    logger.info("UUID migration complete")


def _migrate_artifact_versions_schema(conn: sqlite3.Connection) -> None:
    """Fix todo_artifact_versions if it still has the old id INTEGER PRIMARY KEY schema."""
    if not _table_exists(conn, "todo_artifact_versions"):
        return
    columns = _table_columns(conn, "todo_artifact_versions")
    if "version_id" in columns:
        return

    logger.info("Fixing todo_artifact_versions schema (id INTEGER → version_id + id TEXT)")

    slug_to_id: dict[str, str] = {}
    if "id" in _table_columns(conn, "roadmap"):
        for row_id, slug, status in conn.execute("SELECT id, slug, status FROM roadmap").fetchall():
            if status != "delivered" or slug not in slug_to_id:
                slug_to_id[str(slug)] = str(row_id)

    conn.execute(
        "CREATE TABLE todo_artifact_versions_new ("
        "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, "
        "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
        "created_at TEXT NOT NULL)"
    )
    for slug, name, content, digest, updated_by, created_at in conn.execute(
        "SELECT slug, name, content, digest, updated_by, created_at FROM todo_artifact_versions"
    ).fetchall():
        row_id = slug_to_id.get(str(slug), _generate_id())
        conn.execute(
            "INSERT INTO todo_artifact_versions_new "
            "(id, slug, name, content, digest, updated_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row_id, slug, name, content, digest, updated_by, created_at),
        )
    conn.execute("DROP TABLE todo_artifact_versions")
    conn.execute("ALTER TABLE todo_artifact_versions_new RENAME TO todo_artifact_versions")
    conn.commit()
    logger.info("todo_artifact_versions schema fix complete")


def _migrate_foreign_key_schema(conn: sqlite3.Connection) -> None:
    """Ensure child tables reference roadmap(id) with ON DELETE CASCADE."""

    state_sql = _table_sql(conn, "todo_state").upper()
    if _table_exists(conn, "todo_state") and "ON DELETE CASCADE" not in state_sql:
        conn.execute(
            "CREATE TABLE todo_state_new ("
            "id TEXT PRIMARY KEY REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO todo_state_new (id, slug, state, created_at, updated_at) "
            "SELECT id, slug, state, created_at, updated_at FROM todo_state"
        )
        conn.execute("DROP TABLE todo_state")
        conn.execute("ALTER TABLE todo_state_new RENAME TO todo_state")

    artifact_sql = _table_sql(conn, "todo_artifacts").upper()
    if _table_exists(conn, "todo_artifacts") and "ON DELETE CASCADE" not in artifact_sql:
        conn.execute(
            "CREATE TABLE todo_artifacts_new ("
            "id TEXT NOT NULL REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '', "
            "updated_by TEXT, updated_at TEXT, PRIMARY KEY (id, name))"
        )
        conn.execute(
            "INSERT INTO todo_artifacts_new (id, slug, name, content, digest, updated_by, updated_at) "
            "SELECT id, slug, name, content, digest, updated_by, updated_at FROM todo_artifacts"
        )
        conn.execute("DROP TABLE todo_artifacts")
        conn.execute("ALTER TABLE todo_artifacts_new RENAME TO todo_artifacts")

    versions_sql = _table_sql(conn, "todo_artifact_versions").upper()
    if _table_exists(conn, "todo_artifact_versions") and "ON DELETE CASCADE" not in versions_sql:
        conn.execute(
            "CREATE TABLE todo_artifact_versions_new ("
            "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "id TEXT NOT NULL REFERENCES roadmap(id) ON DELETE CASCADE, "
            "slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO todo_artifact_versions_new "
            "(version_id, id, slug, name, content, digest, updated_by, created_at) "
            "SELECT version_id, id, slug, name, content, digest, updated_by, created_at "
            "FROM todo_artifact_versions"
        )
        conn.execute("DROP TABLE todo_artifact_versions")
        conn.execute("ALTER TABLE todo_artifact_versions_new RENAME TO todo_artifact_versions")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_av_id_name ON todo_artifact_versions(id, name, created_at)")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_roadmap_slug_active "
        "ON roadmap(slug) WHERE status IN ('active', 'icebox')"
    )
    conn.commit()


def _migrate_roadmap_tombstone_columns(conn: sqlite3.Connection) -> None:
    """Additively add the soft-delete tombstone columns to a pre-existing roadmap table.

    Idempotent: each column is added only when absent, leaving existing rows
    untouched. No uniqueness-index change — ``removed`` already sits outside the
    ``status IN ('active', 'icebox')`` partial-unique predicate.
    """
    columns = _table_columns(conn, "roadmap")
    for column in ("removed_at", "prev_status", "removed_deps"):
        if column not in columns:
            conn.execute(f"ALTER TABLE roadmap ADD COLUMN {column} TEXT")  # guard: raw-sql
    conn.commit()


def _migrate_roadmap_pending_purge_paths(conn: sqlite3.Connection) -> None:
    """Additively add the durable purge-retry path column to roadmap rows."""
    columns = _table_columns(conn, "roadmap")
    if "pending_purge_paths" not in columns:
        conn.execute("ALTER TABLE roadmap ADD COLUMN pending_purge_paths TEXT")  # guard: raw-sql
    conn.commit()


def _migrate_roadmap_ordering_columns(conn: sqlite3.Connection) -> None:
    """Ensure derived-ordering metadata and remove legacy manual position."""
    columns = _table_columns(conn, "roadmap")
    if "ready_since" not in columns:
        conn.execute("ALTER TABLE roadmap ADD COLUMN ready_since TEXT")  # guard: raw-sql
        columns = _table_columns(conn, "roadmap")

    if "position" in columns:
        keep_columns = [
            "id",
            "slug",
            "ready_since",
            "group_slug",
            "description",
            "status",
            "delivered_at",
            "delivered_commit",
            "children",
            "created_at",
            "updated_at",
            "removed_at",
            "prev_status",
            "removed_deps",
            "pending_purge_paths",
        ]
        conn.execute(
            "CREATE TABLE roadmap_new ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, "
            "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
            "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "removed_at TEXT, prev_status TEXT, removed_deps TEXT, pending_purge_paths TEXT)"
        )
        column_list = ", ".join(keep_columns)
        conn.execute(
            f"INSERT INTO roadmap_new ({column_list}) SELECT {column_list} FROM roadmap"  # guard: raw-sql
        )
        conn.execute("DROP TABLE roadmap")
        conn.execute("ALTER TABLE roadmap_new RENAME TO roadmap")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_roadmap_slug_active "
        "ON roadmap(slug) WHERE status IN ('active', 'icebox')"
    )
    conn.commit()


def _purge_holder_payload(conn: sqlite3.Connection) -> None:
    """Enforce holder rows as structure only: no state, input artifact only."""
    if not _table_exists(conn, "roadmap"):
        return

    holder_ids = (
        "SELECT DISTINCT parent.id FROM roadmap parent "
        "JOIN roadmap child ON child.group_slug = parent.slug "
        "WHERE parent.status != 'removed' "
        "AND child.status != 'removed' "
        "AND child.slug != parent.slug"
    )
    if _table_exists(conn, "todo_state"):
        conn.execute(f"DELETE FROM todo_state WHERE id IN ({holder_ids})")  # guard: raw-sql
    if _table_exists(conn, "todo_artifacts"):
        conn.execute(f"DELETE FROM todo_artifacts WHERE name != 'input' AND id IN ({holder_ids})")  # guard: raw-sql
    if _table_exists(conn, "todo_artifact_versions"):
        conn.execute(
            f"DELETE FROM todo_artifact_versions WHERE name != 'input' AND id IN ({holder_ids})"  # guard: raw-sql
        )
    conn.commit()


def _migrate_bug_artifact_to_input(conn: sqlite3.Connection) -> None:
    """Collapse the legacy ``bug`` artifact into ``input``.

    Kind is authoritative (``kind == "bug"`` drives the fix lane); the bug report
    now lives in the universal ``input`` artifact. Rename existing rows where the
    slug has no ``input`` yet, then drop any leftover ``bug`` rows. Idempotent —
    re-running finds no ``bug`` rows.
    """
    if not _table_exists(conn, "todo_artifacts"):
        return
    conn.execute(  # guard: raw-sql - one-time artifact-name collapse on existing local DBs
        "UPDATE todo_artifacts SET name = 'input' "
        "WHERE name = 'bug' AND slug NOT IN (SELECT slug FROM todo_artifacts WHERE name = 'input')"
    )
    conn.execute("DELETE FROM todo_artifacts WHERE name = 'bug'")  # guard: raw-sql


def _bootstrap_todos_db(db_path: str) -> None:
    """Run sync migrations and ensure the ORM schema exists."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        if _table_exists(conn, "roadmap"):
            _migrate_to_uuid_schema(conn)
        _migrate_artifact_versions_schema(conn)
        if _table_exists(conn, "roadmap"):
            _migrate_foreign_key_schema(conn)
            _migrate_roadmap_tombstone_columns(conn)
            _migrate_roadmap_pending_purge_paths(conn)
            _migrate_roadmap_ordering_columns(conn)
            _purge_holder_payload(conn)
        _migrate_bug_artifact_to_input(conn)
        conn.commit()
    finally:
        conn.close()

    sync_engine = create_sync_db_engine(db_path)
    try:
        SQLModel.metadata.create_all(sync_engine, tables=TODOS_DB_TABLES)
    finally:
        sync_engine.dispose()

    maybe_auto_import_legacy_markdown_todos(db_path)


class TodosDbBase:
    """Database base class for the todos lifecycle store."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db_path = Path(db_path)
        self.conn: aiosqlite.Connection | None = None
        self._engine: AsyncEngine | None = None
        self._sync_engine: Engine | None = None
        self._sessionmaker: async_sessionmaker[SqlAsyncSession] | None = None
        self._sync_sessionmaker: sessionmaker[SqlSession] | None = None
        self._on_mutation: Callable[[str, Mapping[str, object] | None], None] = _default_on_mutation
        self._on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None] = _default_on_phase_transition

    def on_committed(self, event_hint: str = "todo_updated", event_data: Mapping[str, object] | None = None) -> None:
        """Signal that a caller-managed transaction has committed.

        Use this when the caller owns the session (e.g. multi-step transactions
        in route handlers) and needs to notify the mutation boundary after commit,
        without accessing the protected _on_mutation attribute directly.
        """
        self._on_mutation(event_hint, event_data)

    def notify_phase_transition(
        self,
        slug: str,
        prior_lifecycle_phase: str,
        new_lifecycle_phase: str,
        state_payload: Mapping[str, object],
    ) -> None:
        """Signal that a committed state write changed lifecycle phase."""
        self._on_phase_transition(slug, prior_lifecycle_phase, new_lifecycle_phase, state_payload)

    async def initialize(self) -> None:
        """Bootstrap schema and initialize async + sync runtime access."""
        _bootstrap_todos_db(self.db_path)

        self._engine = create_async_db_engine(self.db_path)
        self._sync_engine = create_sync_db_engine(self.db_path)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)
        self._sync_sessionmaker = sessionmaker(self._sync_engine, expire_on_commit=False, class_=SqlSession)

        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row

    def initialize_sync(self) -> None:
        """Sync schema bootstrap using the shared factory.

        Also sets up the async engine + sessionmaker so a single instance
        cached by ``get_todos_db_sync`` is fully usable from async callers
        too. Without this, the factory cache becomes order-sensitive:
        sync-first callers leave async runtime fields ``None``, and the
        next async caller gets the same cached instance and fails with
        "TodosDb not initialized" even though the file is on disk.
        """
        _bootstrap_todos_db(self.db_path)
        self._sync_engine = create_sync_db_engine(self.db_path)
        self._sync_sessionmaker = sessionmaker(self._sync_engine, expire_on_commit=False, class_=SqlSession)
        if self._engine is None:
            self._engine = create_async_db_engine(self.db_path)
        if self._sessionmaker is None:
            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)

    def _session(self) -> SqlAsyncSession:
        """Create an async ORM session from the initialized session factory."""
        if self._sessionmaker is None:
            msg = "TodosDb not initialized - call initialize() first"
            raise RuntimeError(msg)
        return self._sessionmaker()

    def _sync_session(self) -> SqlSession:
        """Create a sync ORM session from the initialized session factory."""
        if self._sync_sessionmaker is None:
            if self._sync_engine is None:
                self.initialize_sync()
            if self._sync_engine is None:
                msg = "TodosDb sync engine not initialized"
                raise RuntimeError(msg)
            self._sync_sessionmaker = sessionmaker(self._sync_engine, expire_on_commit=False, class_=SqlSession)
        return self._sync_sessionmaker()

    def _sync_conn(self) -> sqlite3.Connection:
        """Open a shared-factory-backed synchronous DB-API connection."""
        if self._sync_engine is None:
            self.initialize_sync()
        if self._sync_engine is None:
            msg = "TodosDb sync engine not initialized"
            raise RuntimeError(msg)
        raw_connection = self._sync_engine.raw_connection()
        return cast(sqlite3.Connection, raw_connection)

    async def close(self) -> None:
        """Close open runtime resources."""
        if self.conn is not None:
            await self.conn.close()
            self.conn = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        if self._sync_engine is not None:
            self._sync_engine.dispose()
            self._sync_engine = None
        self._sessionmaker = None
        self._sync_sessionmaker = None
