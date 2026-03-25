# pylint: disable=invalid-name
"""Migration: Add origin_metadata column and populate from adapter_metadata sections."""

import json

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add origin_metadata column; backfill adapter sections from adapter_metadata."""
    await db.execute("ALTER TABLE sessions ADD COLUMN origin_metadata TEXT")  # guard: raw-sql

    # Backfill: copy adapter_metadata platform sections into origin_metadata.
    # No "platform" key — last_input_origin is the authoritative origin field.
    cursor = await db.execute("SELECT session_id, adapter_metadata FROM sessions")  # guard: raw-sql
    rows = await cursor.fetchall()
    for row in rows:
        session_id = row[0]
        adapter_raw = row[1]

        origin: dict[str, object] = {}  # guard: loose-dict - Migration backfill

        if adapter_raw:
            try:
                adapter = json.loads(adapter_raw)
                if isinstance(adapter, dict):
                    for key in ("telegram", "discord", "whatsapp", "redis"):
                        if key in adapter:
                            origin[key] = adapter[key]
            except (json.JSONDecodeError, TypeError):
                pass

        await db.execute(
            "UPDATE sessions SET origin_metadata = ? WHERE session_id = ?",
            (json.dumps(origin), session_id),
        )  # guard: raw-sql
    await db.commit()
