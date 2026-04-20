"""Add summary, human_email, and visibility columns to the mirrors table.

The mirrors table lives in a separate SQLite database (~/.teleclaude/mirrors.db)
managed by teleclaude.mirrors.store. This migration file documents the schema
change; the actual ALTER TABLE logic is applied by _ensure_schema in store.py
since the mirrors DB uses raw sqlite3, not the aiosqlite migration runner.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """No-op for the main DB — mirrors schema is managed by store.py."""


async def down(db: aiosqlite.Connection) -> None:
    """No-op for the main DB — mirrors schema is managed by store.py."""
