# pylint: disable=invalid-name  # Migration files use numeric prefixes by convention.
"""Migration: Replace api/redis/hook origins with terminal and strip platform key from origin_metadata."""

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Normalize last_input_origin to real origins only. Remove stale platform key from origin_metadata."""
    await db.execute(
        "UPDATE sessions SET last_input_origin = 'terminal' WHERE last_input_origin IN ('api', 'redis', 'hook')"
    )  # guard: raw-sql
    # Remove the "platform" key from origin_metadata — last_input_origin is authoritative.
    await db.execute(
        "UPDATE sessions SET origin_metadata = json_remove(origin_metadata, '$.platform') "
        "WHERE json_extract(origin_metadata, '$.platform') IS NOT NULL"
    )  # guard: raw-sql
    await db.commit()
