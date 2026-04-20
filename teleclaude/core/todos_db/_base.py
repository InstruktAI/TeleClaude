"""TodosDb base: connection lifecycle, schema bootstrap, and migrations."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
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
        "id TEXT PRIMARY KEY, slug TEXT NOT NULL, position INTEGER NOT NULL, "
        "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    for row in conn.execute("SELECT * FROM roadmap").fetchall():
        new_id = _generate_id()
        conn.execute(
            "INSERT INTO roadmap_new VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, *row),
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
        self._on_mutation: Callable[[str], None] = lambda _event_hint: None

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
        """Sync schema bootstrap using the shared factory (for worker-thread contexts)."""
        _bootstrap_todos_db(self.db_path)
        self._sync_engine = create_sync_db_engine(self.db_path)
        self._sync_sessionmaker = sessionmaker(self._sync_engine, expire_on_commit=False, class_=SqlSession)

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
