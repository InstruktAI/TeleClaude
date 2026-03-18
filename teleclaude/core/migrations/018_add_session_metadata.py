"""Migration: Add session_metadata column."""
# pylint: disable=invalid-name  # Migration filenames are versioned on purpose.


import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add session_metadata column to sessions table."""
    try:
        await db.execute("ALTER TABLE sessions ADD COLUMN session_metadata TEXT")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            return
        raise
