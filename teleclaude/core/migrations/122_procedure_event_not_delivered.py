"""Admit terminal not-delivered procedure events without losing retained inbox state."""

from __future__ import annotations

import aiosqlite

_CREATE_INBOX_SQL = """
CREATE TABLE procedure_event_inbox_new (
    enqueue_order INTEGER PRIMARY KEY AUTOINCREMENT,
    activation_id TEXT NOT NULL UNIQUE,
    responsibility_key TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    home TEXT NOT NULL,
    subject TEXT,
    event_json TEXT NOT NULL,
    identity TEXT NOT NULL CHECK(identity IN ('home', 'subject')),
    attendance TEXT NOT NULL CHECK(attendance IN ('attended', 'unattended')),
    event_delivery TEXT NOT NULL CHECK(event_delivery IN ('sequential', 'batched')),
    interruptible INTEGER NOT NULL CHECK(interruptible IN (0, 1)),
    assigned_session_id TEXT,
    outcome TEXT NOT NULL DEFAULT 'pending' CHECK(outcome IN ('pending', 'delivered', 'failed', 'suspended', 'not_delivered')),
    outcome_reason TEXT,
    accepted_at TEXT NOT NULL,
    terminal_at TEXT,
    CHECK(
        (outcome IN ('pending', 'suspended') AND terminal_at IS NULL)
        OR (outcome IN ('delivered', 'failed', 'not_delivered') AND terminal_at IS NOT NULL)
    )
)
"""
_COPY_INBOX_SQL = """
INSERT INTO procedure_event_inbox_new (
    enqueue_order, activation_id, responsibility_key, procedure_id, home, subject,
    event_json, identity, attendance, event_delivery, interruptible, assigned_session_id,
    outcome, outcome_reason, accepted_at, terminal_at
)
SELECT
    enqueue_order, activation_id, responsibility_key, procedure_id, home, subject,
    event_json, identity, attendance, event_delivery, interruptible, assigned_session_id,
    outcome, outcome_reason, accepted_at, terminal_at
FROM procedure_event_inbox
"""
_AUXILIARY_SQL = """
SELECT sql FROM sqlite_master
WHERE tbl_name = 'procedure_event_inbox'
  AND type IN ('index', 'trigger') AND sql IS NOT NULL
ORDER BY type, name
"""
_SEQUENCE_SQL = "SELECT seq FROM sqlite_sequence WHERE name = 'procedure_event_inbox'"
_CLEAR_SEQUENCE_SQL = "DELETE FROM sqlite_sequence WHERE name = 'procedure_event_inbox'"
_RESTORE_SEQUENCE_SQL = "INSERT INTO sqlite_sequence (name, seq) VALUES ('procedure_event_inbox', ?)"


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild the inbox atomically, preserving row identities, indexes and its committed sequence."""
    async with db.execute("PRAGMA foreign_keys") as cursor:
        setting = await cursor.fetchone()
    foreign_keys = bool(setting and setting[0])
    if foreign_keys:
        await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(_AUXILIARY_SQL) as cursor:
            auxiliary = await cursor.fetchall()
        async with db.execute(_SEQUENCE_SQL) as cursor:
            sequence = await cursor.fetchone()
        await db.execute(_CREATE_INBOX_SQL)
        await db.execute(_COPY_INBOX_SQL)
        await db.execute("DROP TABLE procedure_event_inbox")
        await db.execute("ALTER TABLE procedure_event_inbox_new RENAME TO procedure_event_inbox")
        for (statement,) in auxiliary:
            await db.execute(statement)
        # Explicit row copies cannot recover the high-water mark of previously deleted rows.
        await db.execute(_CLEAR_SEQUENCE_SQL)
        if sequence is not None:
            await db.execute(_RESTORE_SEQUENCE_SQL, (sequence[0],))
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        if foreign_keys:
            await db.execute("PRAGMA foreign_keys=ON")


async def down(db: aiosqlite.Connection) -> None:
    """Retained terminal outcomes migrate forward only."""
    del db
