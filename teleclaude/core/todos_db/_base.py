"""TodosDb base: connection lifecycle and schema bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class TodosDbBase:
    """Database base class for the todos lifecycle store."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Bootstrap schema and open the runtime connection."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
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
