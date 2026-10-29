"""Move the output, operations and reminders tables out of the core database into a store file each.

Each target store receives its tables at the shape the core database's history left them, built from the
source's own DDL, and only the rows the runtime retention window keeps: the backlog stays behind and leaves with
the dropped tables. The copy is idempotent (``INSERT OR IGNORE`` by primary key), so an interrupted run converges
on the next one, and the source tables are dropped only after every retained row is verified present in the
target. The retention predicates below are this migration's own frozen copy: a migration never imports live code.
See ``local/projects/teleclaude/policy/schema-and-migrations``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NamedTuple

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migration_signal import MigrationStore, signal_migration_started

logger = get_logger(__name__)

_RETENTION_WINDOW: Final = timedelta(days=7)
_SOURCE: Final = "main"
_TARGET: Final = "target"

_RETAINED_SESSIONS_SQL: Final = f"""(
    SELECT session_id FROM {_SOURCE}.sessions
    WHERE (closed_at IS NULL AND (lifecycle_status IS NULL OR lifecycle_status != 'closed'))
       OR closed_at >= :closed_since
)"""
_LATEST_GENERATION_SQL: Final = f"""(
    SELECT latest.generation_id FROM {_SOURCE}.output_generations AS latest
    WHERE latest.session_id = s.session_id
    ORDER BY latest.created_at DESC LIMIT 1
)"""


class _Table(NamedTuple):
    """One moved table: its primary key and the rows of it the retention window keeps."""

    name: str
    key: tuple[str, ...]
    keep: str


class _Store(NamedTuple):
    """One target store: its file, the signal that announces its migration and the tables it receives."""

    signal: MigrationStore
    file_name: str
    tables: tuple[_Table, ...]


_STORES: Final = (
    _Store(
        MigrationStore.OUTPUT,
        "output.db",
        (
            _Table(
                "output_generations",
                ("generation_id",),
                f"""(s.created_at >= :cutoff
                    OR (s.session_id IN {_RETAINED_SESSIONS_SQL} AND s.generation_id = {_LATEST_GENERATION_SQL})
                    OR EXISTS (SELECT 1 FROM {_SOURCE}.discord_send_intents AS i
                               WHERE i.generation_id = s.generation_id AND i.status = 'pending'))""",
            ),
            _Table(
                "output_consumer_cursors",
                ("session_id", "consumer"),
                f"(s.updated_at >= :cutoff OR s.session_id IN {_RETAINED_SESSIONS_SQL})",
            ),
            _Table(
                "output_consumer_receipts",
                ("session_id", "consumer", "generation_id"),
                f"""(s.updated_at >= :cutoff
                    OR (s.session_id IN {_RETAINED_SESSIONS_SQL} AND s.generation_id = {_LATEST_GENERATION_SQL}))""",
            ),
            _Table(
                "discord_send_intents",
                ("intent_id",),
                "(s.status NOT IN ('resolved', 'omitted', 'replayed') OR coalesce(s.resolved_at, s.created_at) >= :cutoff)",
            ),
        ),
    ),
    _Store(
        MigrationStore.OPERATIONS,
        "operations.db",
        (
            _Table(
                "operations",
                ("operation_id",),
                """(s.state NOT IN ('completed', 'failed', 'stale', 'cancelled')
                    OR coalesce(s.completed_at, s.updated_at) >= :cutoff)""",
            ),
        ),
    ),
    _Store(
        MigrationStore.REMINDERS,
        "reminders.db",
        (
            _Table("reminders", ("session_id", "slug"), "1"),
            _Table(
                "reminder_entries",
                ("entry_id",),
                f"""(s.occurred_at >= :cutoff
                    OR s.session_id IN {_RETAINED_SESSIONS_SQL}
                    OR s.occurrence_key IN (SELECT occurrence_key FROM {_SOURCE}.reminders)
                    OR s.occurrence_key IN (SELECT claimed_occurrence_key FROM {_SOURCE}.reminders
                                            WHERE claimed_occurrence_key IS NOT NULL))""",
            ),
        ),
    ),
)

# A table that keeps an AUTOINCREMENT sequence: the target continues past every id the source ever issued.
_SEQUENCED_TABLES: Final = frozenset({"reminder_entries"})


async def _main_directory(db: aiosqlite.Connection) -> Path | None:
    """Return the directory of the connection's main database file, or None for a database with no file."""
    async with db.execute("PRAGMA database_list") as cursor:
        for _, name, file in await cursor.fetchall():
            if name == _SOURCE and file:
                return Path(file).parent
    return None


async def _present_tables(db: aiosqlite.Connection) -> set[str]:
    async with db.execute(f"SELECT name FROM {_SOURCE}.sqlite_master WHERE type = 'table'") as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def _scalar(db: aiosqlite.Connection, sql: str, params: Mapping[str, str]) -> int:
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row is not None else 0


async def _create_target_objects(db: aiosqlite.Connection, target_path: Path, tables: tuple[_Table, ...]) -> None:
    """Create every table and index the target lacks, from the source's own DDL."""
    source_ddl: list[tuple[str, str]] = []
    for table in tables:
        async with db.execute(
            f"""
            SELECT name, sql FROM {_SOURCE}.sqlite_master
            WHERE tbl_name = ? AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
            ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name
            """,
            (table.name,),
        ) as cursor:
            source_ddl.extend((row[0], row[1]) for row in await cursor.fetchall())
    async with aiosqlite.connect(target_path) as target:
        async with target.execute("SELECT name FROM sqlite_master") as cursor:
            existing = {row[0] for row in await cursor.fetchall()}
        for name, statement in source_ddl:
            if name not in existing:
                await target.execute(statement)
        await target.commit()


async def _carry_sequence(db: aiosqlite.Connection, table: str) -> None:
    """Continue the target's AUTOINCREMENT sequence past every id the source ever issued."""
    async with db.execute(f"SELECT seq FROM {_SOURCE}.sqlite_sequence WHERE name = ?", (table,)) as cursor:
        source_row = await cursor.fetchone()
    if source_row is None:
        return
    updated = await db.execute(
        f"UPDATE {_TARGET}.sqlite_sequence SET seq = max(seq, ?) WHERE name = ?", (source_row[0], table)
    )
    if updated.rowcount == 0:
        await db.execute(f"INSERT INTO {_TARGET}.sqlite_sequence (name, seq) VALUES (?, ?)", (table, source_row[0]))


async def _move_store(db: aiosqlite.Connection, store: _Store, directory: Path, params: Mapping[str, str]) -> None:
    present = await _present_tables(db)
    tables = tuple(table for table in store.tables if table.name in present)
    if not tables:
        return

    signal_migration_started(store.signal)
    target_path = directory / store.file_name
    await _create_target_objects(db, target_path, tables)

    await db.execute(f"ATTACH DATABASE ? AS {_TARGET}", (str(target_path),))
    try:
        carried: dict[str, int] = {}
        discarded: dict[str, int] = {}
        for table in tables:
            await db.execute(
                f"INSERT OR IGNORE INTO {_TARGET}.{table.name} SELECT s.* FROM {_SOURCE}.{table.name} AS s "
                f"WHERE {table.keep}",
                params,
            )
            kept = await _scalar(db, f"SELECT count(*) FROM {_SOURCE}.{table.name} AS s WHERE {table.keep}", params)
            total = await _scalar(db, f"SELECT count(*) FROM {_SOURCE}.{table.name}", params)
            carried[table.name] = kept
            discarded[table.name] = total - kept
            if table.name in _SEQUENCED_TABLES:
                await _carry_sequence(db, table.name)
        await db.commit()

        for table in tables:
            same_key = " AND ".join(f"d.{column} = s.{column}" for column in table.key)
            missing = await _scalar(
                db,
                f"SELECT count(*) FROM {_SOURCE}.{table.name} AS s WHERE {table.keep} "
                f"AND NOT EXISTS (SELECT 1 FROM {_TARGET}.{table.name} AS d WHERE {same_key})",
                params,
            )
            if missing:
                raise RuntimeError(
                    f"{store.file_name}: {missing} retained {table.name} row(s) are missing from the target; "
                    "source tables kept"
                )

        for table in tables:
            await db.execute(f"DROP TABLE {_SOURCE}.{table.name}")
        await db.commit()
    finally:
        # A failed run leaves no open transaction to block the detach; the source tables are still in place.
        await db.rollback()
        await db.execute(f"DETACH DATABASE {_TARGET}")
    logger.info("store_tables_moved", store=store.file_name, carried=carried, discarded=discarded)


async def up(db: aiosqlite.Connection) -> None:
    """Move each store's tables that are still in the core database, retained rows only."""
    directory = await _main_directory(db)
    if directory is None:
        return
    now = datetime.now(UTC)
    cutoff = now - _RETENTION_WINDOW
    params = {
        "cutoff": cutoff.isoformat(),
        "closed_since": cutoff.strftime("%Y-%m-%d %H:%M:%S.%f"),
    }
    await db.commit()
    for store in _STORES:
        await _move_store(db, store, directory, params)
