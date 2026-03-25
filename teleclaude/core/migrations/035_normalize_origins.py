# pylint: disable=invalid-name  # Migration files use numeric prefixes by convention.
"""Migration: Replace api/redis/hook origins with terminal."""

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Normalize last_input_origin and origin_metadata platform to real origins only."""
    await db.execute(
        "UPDATE sessions SET last_input_origin = 'terminal' WHERE last_input_origin IN ('api', 'redis', 'hook')"
    )  # guard: raw-sql
    await db.execute(
        "UPDATE sessions SET origin_metadata = json_replace(origin_metadata, '$.platform', 'terminal') "
        "WHERE json_extract(origin_metadata, '$.platform') IN ('api', 'redis', 'hook')"
    )  # guard: raw-sql
    await db.commit()
