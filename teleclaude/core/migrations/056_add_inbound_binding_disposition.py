"""Mark delivered inbound rows that predate durable turn binding.

Migration 052's ``applied_at`` timestamp is this host's binding cutover. The
datetime normalization is required because app-written ``created_at`` values
and SQLite ``CURRENT_TIMESTAMP`` use different ISO-8601 separators.
"""

from __future__ import annotations

import aiosqlite

_LEGACY_PRE_CUTOVER = "legacy_pre_cutover"


async def up(db: aiosqlite.Connection) -> None:
    """Add the disposition field and backfill pre-cutover unbound rows."""
    async with db.execute("SELECT name FROM pragma_table_info('inbound_queue')") as cursor:
        rows = await cursor.fetchall()
    existing_columns = {str(row[0]) for row in rows}
    if "binding_disposition" not in existing_columns:
        await db.execute("ALTER TABLE inbound_queue ADD COLUMN binding_disposition TEXT")  # guard: raw-sql

    await db.execute(
        """
        UPDATE inbound_queue
        SET binding_disposition = ?
        WHERE status = 'delivered'
          AND binding_disposition IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM accepted_turn_bindings
              WHERE accepted_turn_bindings.inbound_queue_id = inbound_queue.id
          )
          AND datetime(created_at) < (
              SELECT datetime(applied_at)
              FROM schema_migrations
              WHERE version = '052_add_accepted_turn_bindings'
          )
        """,
        (_LEGACY_PRE_CUTOVER,),
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
