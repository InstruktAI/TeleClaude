"""Retire the cutover bookkeeping and the platform help desk kind from stored sessions and bindings."""

from __future__ import annotations

import aiosqlite

_TABLE_INFO_SQL = "PRAGMA table_info(conversation_bindings)"
_HOST_COLUMN = "host"
_DROP_HOST_SQL = "ALTER TABLE conversation_bindings DROP COLUMN host"
_DROP_ADOPTION_SQL = "DROP TABLE IF EXISTS conversation_bindings_adoption"
_DROP_ORPHANS_SQL = "DROP TABLE IF EXISTS conversation_binding_orphans"
# The cutover's activation and start times, and the per-computer export marks of the changeover.
_DELETE_CUTOVER_SETTINGS_SQL = (
    "DELETE FROM system_settings WHERE key IN ('conversation_routing_activated_at', 'conversation_routing_started_at')"
    " OR key LIKE 'conversation_changeover_exported:%'"
)
# The platform desk kind no longer exists: a stamp naming it is no stamp, and a binding to it binds nothing.
_DROP_PLATFORM_STAMPS_SQL = (
    "UPDATE sessions SET origin_metadata = json_remove(origin_metadata, '$.endpoint')"
    " WHERE json_extract(origin_metadata, '$.endpoint.desk_kind') = 'platform'"
)
_DELETE_PLATFORM_BINDINGS_SQL = (
    "DELETE FROM conversation_bindings WHERE json_extract(endpoint, '$.desk_kind') = 'platform'"
)


async def up(db: aiosqlite.Connection) -> None:
    """Drop the tables and settings only the cutover read, and the binding column a remote host used."""
    await db.execute(_DROP_ADOPTION_SQL)  # guard: raw-sql
    await db.execute(_DROP_ORPHANS_SQL)  # guard: raw-sql
    async with db.execute(_TABLE_INFO_SQL) as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _HOST_COLUMN in columns:
        await db.execute(_DROP_HOST_SQL)  # guard: raw-sql
    await db.execute(_DELETE_CUTOVER_SETTINGS_SQL)  # guard: raw-sql
    await db.execute(_DROP_PLATFORM_STAMPS_SQL)  # guard: raw-sql
    await db.execute(_DELETE_PLATFORM_BINDINGS_SQL)  # guard: raw-sql
    await db.commit()
