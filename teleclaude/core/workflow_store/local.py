"""Local SQLite-specific validation reads owned by the local adapter."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.core.workflow_store.types import (
    StoreIntegrityStatus,
    StorePresence,
    StorePresenceKind,
    TransferResult,
    TransferSource,
)

_STATUS_VALUES = (TodoStatus.ACTIVE, TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED)
_REMOTE_EXECUTABLE_OPTION = "--exe"
_UNKNOWN_TRANSFER_RESULT = "target returned an invalid todo sync response"
_DATABASE_MISSING_DETAIL = "project todo database is missing on this computer"
_READ_ONLY_URI_SUFFIX = "?mode=ro"
_INTEGRITY_CHECK_QUERY = "PRAGMA integrity_check"
_SCHEMA_VERSION_QUERY = "PRAGMA schema_version"
_STATUS_ROWS_QUERY_PREFIX = "SELECT r.slug, r.status, r.delivered_commit FROM "
_STATUS_ROWS_QUERY_MIDDLE = " r JOIN todo_state ts ON ts.slug = r.slug WHERE r.status IN (?, ?, ?, ?)"
_NO_SUCH_TABLE_DETAIL = "no such table"


class _TodoOwnerTable(StrEnum):
    CURRENT = "todo"
    LEGACY = "roadmap"


@dataclass(frozen=True)
class _LocalTransferSource:
    """Opaque local SQLite source for the existing incremental transfer tool."""

    _path: Path

    async def sync_to(self, tool_path: Path, destination: str, remote_tool_path: str) -> TransferResult:
        process = await asyncio.create_subprocess_exec(
            str(tool_path),
            str(self._path),
            destination,
            _REMOTE_EXECUTABLE_OPTION,
            remote_tool_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode is None:
            raise RuntimeError(_UNKNOWN_TRANSFER_RESULT)
        return TransferResult(process.returncode, stderr)


def get_local_transfer_source(project_root: str | Path) -> TransferSource | None:
    """Resolve an opaque existing local source without bootstrapping it."""
    path = todos_db_path(project_root)
    return _LocalTransferSource(path) if path.is_file() else None


def local_database_location(project_root: str | Path) -> str | None:
    """Resolve a local path for the remote todo-sync helper's transport reply."""
    path = todos_db_path(project_root)
    return str(path)


def check_local_database_integrity(project_root: str | Path) -> tuple[StoreIntegrityStatus, str]:
    """Check a local database read-only, returning `(status, detail)`."""
    database_path = local_database_location(project_root)
    if database_path is None:
        return StoreIntegrityStatus.ABSENT, _DATABASE_MISSING_DETAIL
    if not Path(database_path).is_file():
        return StoreIntegrityStatus.ABSENT, _DATABASE_MISSING_DETAIL
    database_uri = Path(database_path).as_uri() + _READ_ONLY_URI_SUFFIX
    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            row = connection.execute(_INTEGRITY_CHECK_QUERY).fetchone()
    except (OSError, sqlite3.Error) as error:
        return StoreIntegrityStatus.FAILED, str(error) or type(error).__name__
    if row is None:
        return StoreIntegrityStatus.FAILED, _UNKNOWN_TRANSFER_RESULT
    result = str(row[0])
    status = StoreIntegrityStatus.OK if result == StoreIntegrityStatus.OK.value else StoreIntegrityStatus.FAILED
    return status, result


def local_store_presence(project_root: str | Path) -> StorePresence:
    """Observe local store presence without creating or migrating it."""
    try:
        path = todos_db_path(project_root)
    except FileNotFoundError:
        return StorePresence(StorePresenceKind.ABSENT)
    if not path.is_file():
        return StorePresence(StorePresenceKind.ABSENT)
    try:
        with sqlite3.connect(path.as_uri() + _READ_ONLY_URI_SUFFIX, uri=True) as connection:
            connection.execute(_SCHEMA_VERSION_QUERY).fetchone()
    except sqlite3.Error as exc:
        return StorePresence(StorePresenceKind.INVALID, str(exc))
    return StorePresence(StorePresenceKind.PRESENT)


def read_local_validation_status_rows(project_root: str | Path) -> list[tuple[str, str, str | None]] | None:
    """Read lifecycle-marker validation rows without ORM bootstrap.

    None means no local store is reachable. A present but corrupt database
    raises its SQLite error so validation preserves its fail-visible behavior.
    """
    try:
        path = todos_db_path(project_root)
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None

    connection = sqlite3.connect(path.as_uri() + _READ_ONLY_URI_SUFFIX, uri=True)
    try:
        try:
            rows = _read_status_rows(connection, _TodoOwnerTable.CURRENT)
        except sqlite3.OperationalError as exc:
            if _NO_SUCH_TABLE_DETAIL not in str(exc):
                raise
            try:
                rows = _read_status_rows(connection, _TodoOwnerTable.LEGACY)
            except sqlite3.OperationalError as legacy_exc:
                if _NO_SUCH_TABLE_DETAIL in str(legacy_exc):
                    return []
                raise
    finally:
        connection.close()

    return [
        (slug, status, delivered_commit if isinstance(delivered_commit, str) else None)
        for slug, status, delivered_commit in rows
        if isinstance(slug, str) and isinstance(status, str)
    ]


def _read_status_rows(
    connection: sqlite3.Connection,
    owner_table: _TodoOwnerTable,
) -> Sequence[tuple[object, object, object]]:
    """Read the current or legacy owner table, selected only by this adapter."""
    return connection.execute(
        f"{_STATUS_ROWS_QUERY_PREFIX}{owner_table.value}{_STATUS_ROWS_QUERY_MIDDLE}",
        _STATUS_VALUES,
    ).fetchall()
