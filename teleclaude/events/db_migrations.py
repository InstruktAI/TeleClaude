"""Forward migrations of the events database: stored event data is brought to the current model on open.

The events database holds data the platform owns: notification rows, quarantined
events and correlation windows. Each migration here brings an earlier stored shape
forward so that readers know only the current one. Every step is idempotent.
"""

from __future__ import annotations

import json

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventHomeMarker, EventHomeOwnerMarker
from teleclaude.events.renames import TYPE_RENAMES
from teleclaude.events.wire import stream_event_from_envelope_dump

logger = get_logger(__name__)

_TABLE_COLUMNS_SQL = "PRAGMA table_info({table})"
_RENAME_COLUMN_SQL = "ALTER TABLE {table} RENAME COLUMN {earlier} TO {current}"
_ADD_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN {column} TEXT"
_BACKFILL_COLUMN_SQL = "UPDATE {table} SET {column} = ? WHERE {column} IS NULL"
_RENAME_TYPE_SQL = "UPDATE {table} SET event_type = ? WHERE event_type = ?"
_SELECT_QUARANTINED_BODIES_SQL = "SELECT id, envelope_json FROM quarantined_events"
_UPDATE_QUARANTINED_BODY_SQL = "UPDATE quarantined_events SET envelope_json = ? WHERE id = ?"
_QUARANTINE_BODY_UNREADABLE = "quarantined event body could not be brought forward"

_NOTIFICATIONS = "notifications"
_HOME_COLUMN = "home"
_HOME_OWNER_COLUMN = "home_owner"
_NOTIFICATION_COLUMN_RENAMES = (("subject", _HOME_COLUMN), ("subject_owner", _HOME_OWNER_COLUMN))
_NOTIFICATION_COLUMN_BACKFILLS = (
    (_HOME_COLUMN, EventHomeMarker.UNKNOWN.value),
    (_HOME_OWNER_COLUMN, EventHomeOwnerMarker.UNRESOLVED.value),
)
_CORRELATION_WINDOWS = "correlation_windows"
_EARLIER_WINDOW_INDEXES = ("idx_correlation_windows", "idx_correlation_windows_subject")
_DROP_INDEX_SQL = "DROP INDEX IF EXISTS {index}"
_DROP_COLUMN_SQL = "ALTER TABLE {table} DROP COLUMN {column}"
_EARLIER_WINDOW_SUBJECT_COLUMN = "subject"
_EARLIER_WINDOW_ENTITY_COLUMN = "entity"
_WINDOW_KEY_COLUMN_RENAMES = (("subject", "home"),)
_TYPED_EVENT_TABLES = ("notifications", "quarantined_events", "correlation_windows")
#: The key an earlier envelope dump has and a stream-event dump does not.
_EARLIER_DUMP_MARKER = "event"
_CURRENT_DUMP_MARKER = "legacy"


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await conn.execute(_TABLE_COLUMNS_SQL.format(table=table))
    return {row[1] for row in await cursor.fetchall()}


async def _bring_notification_homes_forward(conn: aiosqlite.Connection) -> None:
    """Rename the notification subject columns to the home they have always held."""
    columns = await _columns(conn, _NOTIFICATIONS)
    for earlier, current in _NOTIFICATION_COLUMN_RENAMES:
        if earlier in columns and current not in columns:
            await conn.execute(_RENAME_COLUMN_SQL.format(table=_NOTIFICATIONS, earlier=earlier, current=current))
    columns = await _columns(conn, _NOTIFICATIONS)
    for column, backfill in _NOTIFICATION_COLUMN_BACKFILLS:
        if column not in columns:
            await conn.execute(_ADD_COLUMN_SQL.format(table=_NOTIFICATIONS, column=column))
        await conn.execute(_BACKFILL_COLUMN_SQL.format(table=_NOTIFICATIONS, column=column), (backfill,))


async def _bring_correlation_windows_forward(conn: aiosqlite.Connection) -> None:
    """Key correlation windows by home and subject instead of the earlier home-as-subject and entity columns.

    Windows are short-lived; earlier rows keep their home and counts, state no subject, and
    expire with the window.
    """
    columns = await _columns(conn, _CORRELATION_WINDOWS)
    for index in _EARLIER_WINDOW_INDEXES:
        await conn.execute(_DROP_INDEX_SQL.format(index=index))
    for earlier, current in _WINDOW_KEY_COLUMN_RENAMES:
        if earlier in columns and current not in columns:
            await conn.execute(_RENAME_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, earlier=earlier, current=current))
    columns = await _columns(conn, _CORRELATION_WINDOWS)
    if _HOME_COLUMN not in columns:
        await conn.execute(_ADD_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_HOME_COLUMN))
        await conn.execute(
            _BACKFILL_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_HOME_COLUMN),
            (EventHomeMarker.UNKNOWN.value,),
        )
    if _EARLIER_WINDOW_SUBJECT_COLUMN not in columns:
        await conn.execute(_ADD_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_EARLIER_WINDOW_SUBJECT_COLUMN))
    if _EARLIER_WINDOW_ENTITY_COLUMN in columns:
        await conn.execute(_DROP_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_EARLIER_WINDOW_ENTITY_COLUMN))


async def _rename_stored_event_types(conn: aiosqlite.Connection) -> None:
    """Rewrite every stored earlier type name to its current name."""
    for table in _TYPED_EVENT_TABLES:
        await conn.executemany(
            _RENAME_TYPE_SQL.format(table=table),
            [(current, earlier) for earlier, current in TYPE_RENAMES.items()],
        )


async def _rewrite_quarantined_bodies(conn: aiosqlite.Connection) -> None:
    """Rewrite each quarantined body from a dump of the earlier envelope into the stored stream-event shape."""
    cursor = await conn.execute(_SELECT_QUARANTINED_BODIES_SQL)
    for row_id, body in await cursor.fetchall():
        try:
            dump: JsonDict = json.loads(body)
            if _CURRENT_DUMP_MARKER in dump or _EARLIER_DUMP_MARKER not in dump:
                continue
            rewritten = stream_event_from_envelope_dump(dump).model_dump_json()
        except (ValueError, KeyError, TypeError):
            logger.warning(_QUARANTINE_BODY_UNREADABLE, row_id=row_id, exc_info=True)
            continue
        await conn.execute(_UPDATE_QUARANTINED_BODY_SQL, (rewritten, row_id))


async def migrate_forward(conn: aiosqlite.Connection) -> None:
    """Bring every stored event shape forward to the current model, in dependency order."""
    await _bring_notification_homes_forward(conn)
    await _bring_correlation_windows_forward(conn)
    await _rename_stored_event_types(conn)
    await _rewrite_quarantined_bodies(conn)
