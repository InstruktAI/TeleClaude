"""Forward migrations of the events database: stored event data is brought to the current model on open.

The events database holds data the platform owns: incident records, correlation
windows and handled-event records. Each migration here brings an earlier stored
shape forward so that readers know only the current one, and drops what the
platform no longer reads. Every step is idempotent.
"""

from __future__ import annotations

import aiosqlite

from teleclaude.core.migration_signal import MigrationStore, signal_migration_started
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.renames import TYPE_RENAMES

_TABLE_COLUMNS_SQL = "PRAGMA table_info({table})"
_RENAME_COLUMN_SQL = "ALTER TABLE {table} RENAME COLUMN {earlier} TO {current}"
_ADD_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN {column} TEXT"
_BACKFILL_COLUMN_SQL = "UPDATE {table} SET {column} = ? WHERE {column} IS NULL"
_RENAME_TYPE_SQL = "UPDATE {table} SET event_type = ? WHERE event_type = ?"
_DROP_TABLE_SQL = "DROP TABLE IF EXISTS {table}"
#: Tables of the retired notification path: stored notification rows and quarantined events.
_RETIRED_TABLES = ("notifications", "quarantined_events")
_HOME_COLUMN = "home"
_CORRELATION_WINDOWS = "correlation_windows"
#: Marks a window row counted before correlation acted only on its own computer's events.
INHERITED_WINDOW_COLUMN = "inherited"
_ADD_INHERITED_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
_MARK_ALL_INHERITED_SQL = "UPDATE {table} SET {column} = 1"
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_INDEX_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?"
_UNMARKED_WINDOW_SQL = "SELECT 1 FROM {table} WHERE {column} = 0 LIMIT 1"
_PLACEHOLDER = "?"
_PLACEHOLDER_SEPARATOR = ", "
_STORED_EARLIER_TYPE_SQL = "SELECT 1 FROM {table} WHERE event_type IN ({placeholders}) LIMIT 1"
#: The table the consumer runtime records handled events in; `EventDB.initialize` creates it after `migrate_forward`.
HANDLED_EVENTS_TABLE = "handled_events"
_EARLIER_WINDOW_INDEXES = ("idx_correlation_windows", "idx_correlation_windows_subject")
_DROP_INDEX_SQL = "DROP INDEX IF EXISTS {index}"
_DROP_COLUMN_SQL = "ALTER TABLE {table} DROP COLUMN {column}"
_EARLIER_WINDOW_SUBJECT_COLUMN = "subject"
_EARLIER_WINDOW_ENTITY_COLUMN = "entity"
_WINDOW_KEY_COLUMN_RENAMES = (("subject", "home"),)
_TYPED_EVENT_TABLES = ("correlation_windows",)


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await conn.execute(_TABLE_COLUMNS_SQL.format(table=table))
    return {row[1] for row in await cursor.fetchall()}


async def _drop_retired_tables(conn: aiosqlite.Connection) -> None:
    """Drop the tables only the retired notification path read; nothing migrates them forward."""
    for table in _RETIRED_TABLES:
        if await _table_exists(conn, table):
            signal_migration_started(MigrationStore.EVENTS)
            await conn.execute(_DROP_TABLE_SQL.format(table=table))


async def _bring_correlation_windows_forward(conn: aiosqlite.Connection) -> None:
    """Key correlation windows by home and subject instead of the earlier home-as-subject and entity columns.

    Windows are short-lived; earlier rows keep their home and counts, state no subject, and
    expire with the window.
    """
    columns = await _columns(conn, _CORRELATION_WINDOWS)
    for index in _EARLIER_WINDOW_INDEXES:
        if await _index_exists(conn, index):
            signal_migration_started(MigrationStore.EVENTS)
            await conn.execute(_DROP_INDEX_SQL.format(index=index))
    for earlier, current in _WINDOW_KEY_COLUMN_RENAMES:
        if earlier in columns and current not in columns:
            signal_migration_started(MigrationStore.EVENTS)
            await conn.execute(_RENAME_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, earlier=earlier, current=current))
    columns = await _columns(conn, _CORRELATION_WINDOWS)
    if _HOME_COLUMN not in columns:
        signal_migration_started(MigrationStore.EVENTS)
        await conn.execute(_ADD_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_HOME_COLUMN))
        await conn.execute(
            _BACKFILL_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_HOME_COLUMN),
            (EventHomeMarker.UNKNOWN.value,),
        )
    if _EARLIER_WINDOW_SUBJECT_COLUMN not in columns:
        signal_migration_started(MigrationStore.EVENTS)
        await conn.execute(_ADD_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_EARLIER_WINDOW_SUBJECT_COLUMN))
    if _EARLIER_WINDOW_ENTITY_COLUMN in columns:
        signal_migration_started(MigrationStore.EVENTS)
        await conn.execute(_DROP_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=_EARLIER_WINDOW_ENTITY_COLUMN))


async def _table_exists(conn: aiosqlite.Connection, table: str) -> bool:
    cursor = await conn.execute(_TABLE_EXISTS_SQL, (table,))
    return (await cursor.fetchone()) is not None


async def _index_exists(conn: aiosqlite.Connection, index: str) -> bool:
    cursor = await conn.execute(_INDEX_EXISTS_SQL, (index,))
    return (await cursor.fetchone()) is not None


async def _mark_inherited_correlation_windows(conn: aiosqlite.Connection) -> None:
    """Mark the window rows counted before consumers existed, once, on the first start that has them.

    Until then every computer counted every computer's events, and a row records no origin, so a
    retained foreign count cannot be told from a local one. The handled-events table is created
    after this step runs, so its absence is the one moment consumers first start; the marked rows
    leave through the windows' ordinary pruning, and nothing is deleted here.
    """
    columns = await _columns(conn, _CORRELATION_WINDOWS)
    if INHERITED_WINDOW_COLUMN not in columns:
        signal_migration_started(MigrationStore.EVENTS)
        await conn.execute(_ADD_INHERITED_COLUMN_SQL.format(table=_CORRELATION_WINDOWS, column=INHERITED_WINDOW_COLUMN))
    if not await _table_exists(conn, HANDLED_EVENTS_TABLE):
        unmarked = await conn.execute(
            _UNMARKED_WINDOW_SQL.format(table=_CORRELATION_WINDOWS, column=INHERITED_WINDOW_COLUMN)
        )
        if await unmarked.fetchone() is not None:
            signal_migration_started(MigrationStore.EVENTS)
            await conn.execute(
                _MARK_ALL_INHERITED_SQL.format(table=_CORRELATION_WINDOWS, column=INHERITED_WINDOW_COLUMN)
            )


async def _rename_stored_event_types(conn: aiosqlite.Connection) -> None:
    """Rewrite every stored earlier type name to its current name."""
    if not TYPE_RENAMES:
        return
    for table in _TYPED_EVENT_TABLES:
        stored = await conn.execute(
            _STORED_EARLIER_TYPE_SQL.format(
                table=table, placeholders=_PLACEHOLDER_SEPARATOR.join(_PLACEHOLDER for _ in TYPE_RENAMES)
            ),
            tuple(TYPE_RENAMES),
        )
        if await stored.fetchone() is None:
            continue
        signal_migration_started(MigrationStore.EVENTS)
        await conn.executemany(
            _RENAME_TYPE_SQL.format(table=table),
            [(current, earlier) for earlier, current in TYPE_RENAMES.items()],
        )


async def migrate_forward(conn: aiosqlite.Connection) -> None:
    """Bring every stored event shape forward to the current model, in dependency order."""
    await _drop_retired_tables(conn)
    await _bring_correlation_windows_forward(conn)
    await _mark_inherited_correlation_windows(conn)
    await _rename_stored_event_types(conn)
