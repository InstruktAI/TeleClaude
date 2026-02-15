"""Add session_listeners table for durable PUB-SUB notifications.

Listeners were previously in-memory and lost on daemon restart.
SQLite persistence ensures notifications survive restarts.
"""

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS session_listeners (
            target_session_id TEXT NOT NULL,
            caller_session_id TEXT NOT NULL,
            caller_tmux_session TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            PRIMARY KEY (target_session_id, caller_session_id)
        )
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_listeners_caller
            ON session_listeners(caller_session_id)
    """)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_session_listeners_caller")
    await db.execute("DROP TABLE IF EXISTS session_listeners")
    await db.commit()
