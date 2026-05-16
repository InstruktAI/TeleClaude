"""Startup migration for moving hook outbox rows into the dedicated database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import NamedTuple

from teleclaude.core.db.connection_factory import create_sync_db_engine, init_outbox_schema


class _LegacyOutboxRow(NamedTuple):
    """Typed copy of a legacy hook_outbox row loaded from teleclaude.db."""

    id: int
    session_id: str
    event_type: str
    payload: str
    created_at: str | None
    next_attempt_at: str | None
    attempt_count: int
    last_error: str | None
    locked_at: str | None


def _has_legacy_outbox_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'hook_outbox'"  # guard: raw-sql
    ).fetchone()
    return row is not None


def _load_legacy_rows(conn: sqlite3.Connection) -> list[_LegacyOutboxRow]:
    rows = conn.execute(
        "SELECT id, session_id, event_type, payload, created_at, next_attempt_at, "
        "attempt_count, last_error, locked_at FROM hook_outbox ORDER BY id"  # guard: raw-sql
    ).fetchall()
    return [
        _LegacyOutboxRow(
            id=int(row[0]),
            session_id=str(row[1]),
            event_type=str(row[2]),
            payload=str(row[3]),
            created_at=str(row[4]) if row[4] is not None else None,
            next_attempt_at=str(row[5]) if row[5] is not None else None,
            attempt_count=int(row[6]) if row[6] is not None else 0,
            last_error=str(row[7]) if row[7] is not None else None,
            locked_at=str(row[8]) if row[8] is not None else None,
        )
        for row in rows
    ]


def _ensure_outbox_schema(outbox_db_path: str) -> None:
    Path(outbox_db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_sync_db_engine(outbox_db_path)
    try:
        init_outbox_schema(engine)
    finally:
        engine.dispose()


def _copy_rows_to_outbox(outbox_db_path: str, rows: list[_LegacyOutboxRow]) -> int:
    """Copy legacy rows into the outbox DB without explicit IDs and return the inserted count."""
    conn = sqlite3.connect(outbox_db_path)
    try:
        before_count = conn.execute("SELECT COUNT(*) FROM hook_outbox").fetchone()[0]  # guard: raw-sql
        conn.executemany(
            "INSERT INTO hook_outbox "  # guard: raw-sql
            "(session_id, event_type, payload, created_at, next_attempt_at, attempt_count, last_error, locked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row.session_id,
                    row.event_type,
                    row.payload,
                    row.created_at,
                    row.next_attempt_at,
                    row.attempt_count,
                    row.last_error,
                    row.locked_at,
                )
                for row in rows
            ],
        )
        conn.commit()
        after_count = conn.execute("SELECT COUNT(*) FROM hook_outbox").fetchone()[0]  # guard: raw-sql
        return int(after_count) - int(before_count)
    finally:
        conn.close()


def migrate_outbox_on_startup(main_db_path: str, outbox_db_path: str) -> None:
    """Copy legacy hook_outbox rows into the dedicated outbox DB and drop the old table.

    The drop is gated: the legacy table is only removed when every row has been
    verified as inserted into the target database.  This prevents data loss on
    interrupted startups where the receiver may have already written rows to
    hook_outbox.db with IDs that collide with the legacy integer PKs.
    """
    Path(main_db_path).parent.mkdir(parents=True, exist_ok=True)
    main_conn = sqlite3.connect(main_db_path)
    try:
        if not _has_legacy_outbox_table(main_conn):
            return

        _ensure_outbox_schema(outbox_db_path)
        rows = _load_legacy_rows(main_conn)
        if rows:
            inserted = _copy_rows_to_outbox(outbox_db_path, rows)
            if inserted != len(rows):
                msg = (
                    f"Outbox migration incomplete: expected {len(rows)} rows "
                    f"but only {inserted} were inserted. Legacy table preserved."
                )
                raise RuntimeError(msg)

        main_conn.execute("DROP TABLE hook_outbox")  # guard: raw-sql
        main_conn.commit()
    finally:
        main_conn.close()


__all__ = ["migrate_outbox_on_startup"]
