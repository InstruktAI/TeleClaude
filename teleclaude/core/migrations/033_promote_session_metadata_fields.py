# pylint: disable=invalid-name
"""Migration: Promote system_role and job from session_metadata JSON to first-class columns."""

import json

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add system_role and job columns; backfill from session_metadata JSON."""
    await db.execute("ALTER TABLE sessions ADD COLUMN system_role TEXT")  # guard: raw-sql
    await db.execute("ALTER TABLE sessions ADD COLUMN job TEXT")  # guard: raw-sql

    # Backfill from existing session_metadata JSON blob
    cursor = await db.execute(
        "SELECT session_id, session_metadata FROM sessions WHERE session_metadata IS NOT NULL"
    )  # guard: raw-sql
    rows = await cursor.fetchall()
    for row in rows:
        session_id = row[0]
        raw = row[1]
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        system_role = parsed.get("system_role")
        job = parsed.get("job")
        if system_role or job:
            await db.execute(
                "UPDATE sessions SET system_role = ?, job = ? WHERE session_id = ?",
                (system_role, job, session_id),
            )  # guard: raw-sql
    await db.commit()
