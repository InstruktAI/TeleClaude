"""Idempotent schema and derived-data migrations for the mirrors store.

Every migration here runs on schema init and must be safe to re-run: they bring an
existing mirrors table up to the current shape and realign columns whose values are
derived rather than authored.
"""

from __future__ import annotations

import sqlite3

from teleclaude.constants import WORKER_COMMANDS


def migrate_add_mirror_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add derived-classification columns to existing mirrors tables."""
    for stmt in (
        "ALTER TABLE mirrors ADD COLUMN summary TEXT",
        "ALTER TABLE mirrors ADD COLUMN human_email TEXT",
        "ALTER TABLE mirrors ADD COLUMN visibility TEXT DEFAULT 'private'",
        "ALTER TABLE mirrors ADD COLUMN command TEXT",
        "ALTER TABLE mirrors ADD COLUMN slug TEXT",
        "ALTER TABLE mirrors ADD COLUMN is_agent_spawn INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE mirrors ADD COLUMN derivation_version INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_is_agent_spawn ON mirrors(is_agent_spawn)")
    reconcile_agent_spawn_classification(conn)


def reconcile_agent_spawn_classification(conn: sqlite3.Connection) -> None:
    """Realign stored `is_agent_spawn` with the current worker-command set.

    The flag is derived from the row's launch command, never authored, so a row whose
    stored value disagrees with today's rule is stale rather than intentional. Rows are
    reclassified in place from the persisted `command`, which costs one narrow update
    and leaves `conversation_text` untouched — a `DERIVATION_VERSION` bump would instead
    push every transcript back through full generation, summarizer call included, to
    settle a question the stored column already answers.

    Idempotent: once aligned the predicate matches nothing, so later calls do no work.
    """
    placeholders = ", ".join("?" * len(WORKER_COMMANDS))
    workers = sorted(WORKER_COMMANDS)
    conn.execute(
        f"UPDATE mirrors SET is_agent_spawn = 0 "
        f"WHERE is_agent_spawn = 1 AND (command IS NULL OR command NOT IN ({placeholders}))",
        workers,
    )
    conn.execute(
        f"UPDATE mirrors SET is_agent_spawn = 1 WHERE is_agent_spawn = 0 AND command IN ({placeholders})",
        workers,
    )
