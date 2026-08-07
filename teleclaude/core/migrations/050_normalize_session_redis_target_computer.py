"""Strip the legacy redis.target_computer key from stored session origin metadata."""

from __future__ import annotations

import json

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Remove any leftover ``redis.target_computer`` key — the field is retired."""
    async with db.execute(
        "SELECT session_id, origin_metadata FROM sessions WHERE origin_metadata LIKE '%target_computer%'"
    ) as cursor:
        rows = await cursor.fetchall()

    for session_id, raw in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        redis_section = parsed.get("redis")
        if not isinstance(redis_section, dict) or "target_computer" not in redis_section:
            continue
        del redis_section["target_computer"]
        await db.execute(
            "UPDATE sessions SET origin_metadata = ? WHERE session_id = ?",
            (json.dumps(parsed), session_id),
        )

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """A stripped key cannot be reconstructed — no-op."""
