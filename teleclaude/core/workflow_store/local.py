"""Local SQLite-specific validation reads owned by the local adapter."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.core.workflow_store.types import StorePresence, StorePresenceKind, TransferResult, TransferSource

_STATUS_VALUES = (TodoStatus.ACTIVE, TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED)


@dataclass(frozen=True)
class _LocalTransferSource:
    """Opaque local SQLite source for the existing incremental transfer tool."""

    _path: Path

    async def sync_to(self, tool_path: Path, destination: str, remote_tool_path: str) -> TransferResult:
        process = await asyncio.create_subprocess_exec(
            str(tool_path),
            str(self._path),
            destination,
            "--exe",
            remote_tool_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode is None:
            raise RuntimeError("target returned an invalid todo sync response")
        return TransferResult(process.returncode, stderr)


def get_local_transfer_source(project_root: str | Path) -> TransferSource | None:
    """Resolve an opaque existing local source without bootstrapping it."""
    path = todos_db_path(project_root)
    return _LocalTransferSource(path) if path.is_file() else None


def local_database_location(project_root: str | Path) -> str | None:
    """Resolve a local path for the remote todo-sync helper's transport reply."""
    path = todos_db_path(project_root)
    return str(path) if path.is_file() else None


def check_local_database_integrity(project_root: str | Path) -> tuple[str, str]:
    """Check a local database read-only, returning `(status, detail)`."""
    database_path = local_database_location(project_root)
    if database_path is None:
        return "absent", "project todo database is missing on this computer"
    database_uri = Path(database_path).as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
    except (OSError, sqlite3.Error) as error:
        return "failed", str(error) or type(error).__name__
    if row is None:
        return "failed", "target returned an invalid todo sync response"
    result = str(row[0])
    return ("ok", result) if result == "ok" else ("failed", result)


def local_store_presence(project_root: str | Path) -> StorePresence:
    """Observe local store presence without creating or migrating it."""
    try:
        path = todos_db_path(project_root)
    except FileNotFoundError:
        return StorePresence(StorePresenceKind.ABSENT)
    if not path.is_file():
        return StorePresence(StorePresenceKind.ABSENT)
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA schema_version").fetchone()
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

    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        try:
            rows = _read_status_rows(connection, "todo")
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            try:
                rows = _read_status_rows(connection, "roadmap")
            except sqlite3.OperationalError as legacy_exc:
                if "no such table" in str(legacy_exc):
                    return []
                raise
    finally:
        connection.close()

    return [
        (slug, status, delivered_commit if isinstance(delivered_commit, str) else None)
        for slug, status, delivered_commit in rows
        if isinstance(slug, str) and isinstance(status, str)
    ]


def _read_status_rows(connection: sqlite3.Connection, owner_table: str) -> Sequence[tuple[object, object, object]]:
    """Read the current or legacy owner table, selected only by this adapter."""
    return connection.execute(
        f"SELECT r.slug, r.status, r.delivered_commit FROM {owner_table} r "
        "JOIN todo_state ts ON ts.slug = r.slug "
        "WHERE r.status IN (?, ?, ?, ?)",
        _STATUS_VALUES,
    ).fetchall()
