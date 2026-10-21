"""Withdraw queued deletion intents for retained Discord conversation messages."""

from __future__ import annotations

import aiosqlite

_WITHDRAW_DISCORD_CONVERSATION_DELETIONS_SQL = """
DELETE FROM pending_message_deletions
WHERE adapter_key = 'discord'
  AND deletion_type = 'user_input'
  AND NOT EXISTS (
      SELECT 1
      FROM system_settings
      WHERE system_settings.key = 'discord_listen:' || pending_message_deletions.session_id
        AND system_settings.value = pending_message_deletions.message_id
  )
"""


async def up(db: aiosqlite.Connection) -> None:
    """Withdraw obsolete Discord input cleanup while retaining current Listen here controls."""
    await db.execute(_WITHDRAW_DISCORD_CONVERSATION_DELETIONS_SQL)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Removed deletion intents cannot be reconstructed without risking control deletion."""
    del db
