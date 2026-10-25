"""Create the Discord inbound recovery cursor and start one for every place bound to a still-active session.

A place is a session thread or a Team channel
(``local/projects/teleclaude/spec/domain/integration``). A place's cursor starts at the newest Discord message the
inbound queue still retains as accepted for its sessions; a place with none starts at the queue's retention
horizon, since input accepted after the horizon is still retained and so nothing after it was processed. The
migration runs during the installation's own outage, before the daemon accepts anything, so every message posted
in that outage lies after the start.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Final, cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.inbound.models import DISCORD_DM_KEY_FIELD
from teleclaude.core.integration.discord_inbound_cursor import message_id_of_source_identity, seed_for_place
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import SessionLifecycleStatus

logger = get_logger(__name__)

_CREATE_CURSORS_SQL: Final = """
CREATE TABLE IF NOT EXISTS discord_inbound_cursors (
    place_id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_SELECT_THREAD_SESSIONS_SQL: Final = """
SELECT CAST(json_extract(origin_metadata, '$.discord.thread_id') AS INTEGER), session_id
FROM sessions
WHERE closed_at IS NULL
  AND json_extract(origin_metadata, '$.discord.thread_id') IS NOT NULL
"""
_SELECT_CHANNEL_BINDINGS_SQL: Final = """
SELECT CAST(conversation_key AS INTEGER), session_id
FROM conversation_bindings
WHERE origin = ?
  AND key_field = ?
  AND NOT EXISTS (
      SELECT 1
      FROM sessions
      WHERE sessions.session_id = conversation_bindings.session_id
        AND (sessions.closed_at IS NOT NULL OR sessions.lifecycle_status = ?)
  )
"""
_SELECT_RETAINED_DISCORD_INPUT_SQL: Final = """
SELECT session_id, source_message_id
FROM inbound_queue
WHERE origin = ?
  AND source_message_id IS NOT NULL
"""
_INSERT_CURSOR_SQL: Final = """
INSERT OR IGNORE INTO discord_inbound_cursors (place_id, message_id, updated_at) VALUES (?, ?, ?)
"""
_SEEDED_EVENT: Final = "discord_inbound_cursors_seeded"


async def up(db: aiosqlite.Connection) -> None:
    """Create the cursor table and seed a cursor for each place bound to a still-active session."""
    await db.execute(_CREATE_CURSORS_SQL)

    sessions_by_place: defaultdict[int, set[str]] = defaultdict(set)
    for place_id, session_id in await _place_sessions(db, _SELECT_THREAD_SESSIONS_SQL, ()):
        sessions_by_place[place_id].add(session_id)
    # A Team channel and a direct message share one binding shape; a direct message's cursor is never read.
    channel_parameters = (InputOrigin.DISCORD.value, DISCORD_DM_KEY_FIELD, SessionLifecycleStatus.CLOSED.value)
    for place_id, session_id in await _place_sessions(db, _SELECT_CHANNEL_BINDINGS_SQL, channel_parameters):
        sessions_by_place[place_id].add(session_id)

    newest_by_session: dict[str, int] = {}
    retained = await db.execute(_SELECT_RETAINED_DISCORD_INPUT_SQL, (InputOrigin.DISCORD.value,))
    for session_id, source_message_id in cast(list[tuple[str, str]], await retained.fetchall()):
        message_id = message_id_of_source_identity(source_message_id)
        if message_id is not None:
            newest_by_session[session_id] = max(message_id, newest_by_session.get(session_id, message_id))

    now = datetime.now(UTC)
    for place_id, session_ids in sessions_by_place.items():
        newest = max(
            (newest_by_session[session_id] for session_id in session_ids if session_id in newest_by_session),
            default=None,
        )
        seed = seed_for_place(newest, bound_at=None, now=now)
        await db.execute(_INSERT_CURSOR_SQL, (place_id, seed, now.isoformat()))
    await db.commit()
    logger.info(_SEEDED_EVENT, places=len(sessions_by_place))


async def _place_sessions(db: aiosqlite.Connection, sql: str, parameters: tuple[str, ...]) -> list[tuple[int, str]]:
    """The place id and session id of every row of a query selecting those two columns."""
    cursor = await db.execute(sql, parameters)
    return cast(list[tuple[int, str]], await cursor.fetchall())
