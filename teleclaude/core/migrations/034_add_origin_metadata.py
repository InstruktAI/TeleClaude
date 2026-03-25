# pylint: disable=invalid-name
"""Migration: Add origin_metadata column and populate from adapter_metadata + last_input_origin."""

import json

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add origin_metadata column; backfill platform key from last_input_origin."""
    await db.execute("ALTER TABLE sessions ADD COLUMN origin_metadata TEXT")  # guard: raw-sql

    # Backfill: merge last_input_origin as platform key into origin_metadata,
    # and copy adapter_metadata sections into their platform keys.
    cursor = await db.execute("SELECT session_id, last_input_origin, adapter_metadata FROM sessions")  # guard: raw-sql
    rows = await cursor.fetchall()
    for row in rows:
        session_id = row[0]
        platform = row[1] or "terminal"
        adapter_raw = row[2]

        origin: dict[str, object] = {"platform": platform}  # guard: loose-dict - Migration backfill

        # Copy adapter_metadata platform sections into origin_metadata
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
