"""Add performance indexes on sessions table for common query patterns."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create indexes for frequently filtered/sorted sessions columns."""
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_closed_at ON sessions(closed_at)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_lifecycle_status ON sessions(lifecycle_status)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity DESC)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_native_session_id ON sessions(native_session_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_initiator ON sessions(initiator_session_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name)")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop the performance indexes."""
    await db.execute("DROP INDEX IF EXISTS idx_sessions_closed_at")
    await db.execute("DROP INDEX IF EXISTS idx_sessions_lifecycle_status")
    await db.execute("DROP INDEX IF EXISTS idx_sessions_last_activity")
    await db.execute("DROP INDEX IF EXISTS idx_sessions_native_session_id")
    await db.execute("DROP INDEX IF EXISTS idx_sessions_initiator")
    await db.execute("DROP INDEX IF EXISTS idx_sessions_computer")
    await db.commit()
