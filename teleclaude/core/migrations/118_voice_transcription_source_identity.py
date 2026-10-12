"""Give voice transcriptions the provider identity of the message part they transcribe.

A transcript is accepted into the inbound queue under the part's provider identity, so a redelivered
provider message and a recovered transcription both meet the queue's deduplication. Rows written before
this migration carry no identity and recover as before.
"""

from __future__ import annotations

import aiosqlite

_COLUMNS_SQL = "SELECT name FROM pragma_table_info('voice_transcriptions')"
_ADD_SOURCE_MESSAGE_ID_SQL = "ALTER TABLE voice_transcriptions ADD COLUMN source_message_id TEXT"
_SOURCE_MESSAGE_ID_COLUMN = "source_message_id"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable source identity column when it is absent; every stored transcription keeps its state."""
    async with db.execute(_COLUMNS_SQL) as cursor:
        existing = {str(row[0]) for row in await cursor.fetchall()}
    if _SOURCE_MESSAGE_ID_COLUMN not in existing:
        await db.execute(_ADD_SOURCE_MESSAGE_ID_SQL)
    await db.commit()
