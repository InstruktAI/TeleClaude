"""TodosDb base: connection lifecycle, schema bootstrap, and migrations."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def _generate_id() -> str:
    """Generate a UUID for use as a todo identifier."""
    return str(uuid.uuid4())


def _migrate_to_uuid_schema(conn: sqlite3.Connection) -> None:
    """Migrate from slug-as-PK to id-as-PK schema if needed.

    Detects old schema by checking if roadmap has an 'id' column.
    Creates new tables, copies data with generated UUIDs, swaps.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(roadmap)").fetchall()}
    if "id" in columns:
        return  # Already migrated

    logger.info("Migrating todos.db to UUID-based schema")

    # --- roadmap ---
    conn.execute(
        "CREATE TABLE roadmap_new ("  # guard: raw-sql
        "id TEXT PRIMARY KEY, slug TEXT NOT NULL, position INTEGER NOT NULL, "
        "group_slug TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "delivered_at TEXT, delivered_commit TEXT, children TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    for row in conn.execute("SELECT * FROM roadmap").fetchall():
        new_id = _generate_id()
        conn.execute(
            "INSERT INTO roadmap_new VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  # guard: raw-sql
            (new_id, *row),
        )
    conn.execute("DROP TABLE roadmap")  # guard: raw-sql
    conn.execute("ALTER TABLE roadmap_new RENAME TO roadmap")  # guard: raw-sql

    # Build slug→id mapping for the other tables
    slug_to_id: dict[str, str] = {}
    for row in conn.execute("SELECT id, slug, status FROM roadmap").fetchall():
        rid, rslug, rstatus = row
        if rstatus != "delivered" or rslug not in slug_to_id:
            slug_to_id[rslug] = rid

    # --- todo_state ---
    conn.execute(
        "CREATE TABLE todo_state_new ("  # guard: raw-sql
        "id TEXT PRIMARY KEY, slug TEXT NOT NULL, state TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    for row in conn.execute("SELECT slug, state, created_at, updated_at FROM todo_state").fetchall():
        slug = row[0]
        row_id = slug_to_id.get(slug, _generate_id())
        conn.execute(
            "INSERT OR IGNORE INTO todo_state_new VALUES (?, ?, ?, ?, ?)",  # guard: raw-sql
            (row_id, slug, row[1], row[2], row[3]),
        )
    conn.execute("DROP TABLE todo_state")  # guard: raw-sql
    conn.execute("ALTER TABLE todo_state_new RENAME TO todo_state")  # guard: raw-sql

    # --- todo_artifacts ---
    conn.execute(
        "CREATE TABLE todo_artifacts_new ("  # guard: raw-sql
        "id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, "
        "content TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '', "
        "updated_by TEXT, updated_at TEXT, PRIMARY KEY (id, name))"
    )
    for row in conn.execute(
        "SELECT slug, name, content, digest, updated_by, updated_at FROM todo_artifacts"  # guard: raw-sql
    ).fetchall():
        slug = row[0]
        row_id = slug_to_id.get(slug, _generate_id())
        conn.execute(
            "INSERT OR IGNORE INTO todo_artifacts_new VALUES (?, ?, ?, ?, ?, ?, ?)",  # guard: raw-sql
            (row_id, slug, row[1], row[2], row[3], row[4], row[5]),
        )
    conn.execute("DROP TABLE todo_artifacts")  # guard: raw-sql
    conn.execute("ALTER TABLE todo_artifacts_new RENAME TO todo_artifacts")  # guard: raw-sql

    # --- todo_artifact_versions ---
    old_cols = {r[1] for r in conn.execute("PRAGMA table_info(todo_artifact_versions)").fetchall()}
    if "version_id" not in old_cols:
        conn.execute(
            "CREATE TABLE todo_artifact_versions_new ("  # guard: raw-sql
            "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, "
            "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
            "created_at TEXT NOT NULL)"
        )
        for row in conn.execute(
            "SELECT slug, name, content, digest, updated_by, created_at "  # guard: raw-sql
            "FROM todo_artifact_versions"
        ).fetchall():
            slug = row[0]
            row_id = slug_to_id.get(slug, _generate_id())
            conn.execute(
                "INSERT INTO todo_artifact_versions_new "  # guard: raw-sql
                "(id, slug, name, content, digest, updated_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, slug, row[1], row[2], row[3], row[4], row[5]),
            )
        conn.execute("DROP TABLE todo_artifact_versions")  # guard: raw-sql
        conn.execute("ALTER TABLE todo_artifact_versions_new RENAME TO todo_artifact_versions")  # guard: raw-sql

    conn.commit()
    logger.info("UUID migration complete")


def _migrate_artifact_versions_schema(conn: sqlite3.Connection) -> None:
    """Fix todo_artifact_versions if it still has the old id INTEGER PRIMARY KEY schema.

    Runs independently of the UUID migration so it catches databases where the UUID
    migration already ran but incorrectly skipped this table.
    """
    rows = conn.execute("PRAGMA table_info(todo_artifact_versions)").fetchall()
    if not rows:
        return  # Table not yet created; schema.sql will create it correctly.
    col_names = {r[1] for r in rows}
    if "version_id" in col_names:
        return  # Already correct schema.

    logger.info("Fixing todo_artifact_versions schema (id INTEGER → version_id + id TEXT)")

    # Build slug→id mapping from roadmap for data preservation.
    slug_to_id: dict[str, str] = {}
    roadmap_cols = {r[1] for r in conn.execute("PRAGMA table_info(roadmap)").fetchall()}
    if "id" in roadmap_cols:
        for row in conn.execute("SELECT id, slug, status FROM roadmap").fetchall():
            rid, rslug, rstatus = row
            if rstatus != "delivered" or rslug not in slug_to_id:
                slug_to_id[rslug] = rid

    conn.execute(
        "CREATE TABLE todo_artifact_versions_new ("  # guard: raw-sql
        "version_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, "
        "content TEXT NOT NULL, digest TEXT NOT NULL, updated_by TEXT, "
        "created_at TEXT NOT NULL)"
    )
    for row in conn.execute(
        "SELECT slug, name, content, digest, updated_by, created_at "  # guard: raw-sql
        "FROM todo_artifact_versions"
    ).fetchall():
        slug = row[0]
        row_id = slug_to_id.get(slug, _generate_id())
        conn.execute(
            "INSERT INTO todo_artifact_versions_new "  # guard: raw-sql
            "(id, slug, name, content, digest, updated_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row_id, slug, row[1], row[2], row[3], row[4], row[5]),
        )
    conn.execute("DROP TABLE todo_artifact_versions")  # guard: raw-sql
    conn.execute("ALTER TABLE todo_artifact_versions_new RENAME TO todo_artifact_versions")  # guard: raw-sql
    conn.commit()
    logger.info("todo_artifact_versions schema fix complete")


class TodosDbBase:
    """Database base class for the todos lifecycle store."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Bootstrap schema and open the runtime connection."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Run migration before async schema init (uses sync connection)
        sync_conn = sqlite3.connect(self.db_path)
        try:
            # Check if tables exist before migrating
            tables = {
                r[0]
                for r in sync_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"  # guard: raw-sql
                ).fetchall()
            }
            if "roadmap" in tables:
                _migrate_to_uuid_schema(sync_conn)
            _migrate_artifact_versions_schema(sync_conn)
        finally:
            sync_conn.close()

        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode = WAL")  # guard: raw-sql
        await self.conn.execute("PRAGMA synchronous = NORMAL")  # guard: raw-sql
        await self.conn.execute("PRAGMA busy_timeout = 5000")  # guard: raw-sql
        await self.conn.execute("PRAGMA foreign_keys = ON")  # guard: raw-sql

        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        await self.conn.executescript(schema_sql)  # guard: raw-sql
        await self.conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            await self.conn.close()
            self.conn = None

    def initialize_sync(self) -> None:
        """Sync schema bootstrap using sqlite3 (for non-async contexts and tests)."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL")  # guard: raw-sql
        conn.execute("PRAGMA synchronous = NORMAL")  # guard: raw-sql
        conn.execute("PRAGMA busy_timeout = 5000")  # guard: raw-sql
        conn.execute("PRAGMA foreign_keys = ON")  # guard: raw-sql

        # Check if tables exist before migrating
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"  # guard: raw-sql
            ).fetchall()
        }
        if "roadmap" in tables:
            _migrate_to_uuid_schema(conn)
        _migrate_artifact_versions_schema(conn)

        schema_path = Path(__file__).parent / "schema.sql"
        conn.executescript(schema_path.read_text(encoding="utf-8"))  # guard: raw-sql
        conn.commit()
        conn.close()

    def _sync_conn(self) -> sqlite3.Connection:
        """Open a separate synchronous connection for thread-safe reads.

        Used by the integration state machine which runs in a worker thread.
        WAL mode allows concurrent reads from multiple connections safely.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")  # guard: raw-sql
        conn.execute("PRAGMA busy_timeout = 5000")  # guard: raw-sql
        return conn
