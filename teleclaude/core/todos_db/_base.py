"""TodosDb base: connection lifecycle and schema bootstrap."""

from __future__ import annotations

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
