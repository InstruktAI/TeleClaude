"""Idempotent schema and derived-data migrations for the mirrors store.

Every migration here runs on schema init and must be safe to re-run: they bring an
existing mirrors table up to the current shape and realign columns whose values are
derived rather than authored.
"""

from __future__ import annotations

import sqlite3

from teleclaude.constants import WORKER_COMMANDS
from teleclaude.mirrors.derivation import is_known_launch_command, render_title


def migrate_add_mirror_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add derived-classification columns to existing mirrors tables."""
    _rename_agent_spawn_column(conn)
    for stmt in (
        "ALTER TABLE mirrors ADD COLUMN summary TEXT",
        "ALTER TABLE mirrors ADD COLUMN human_email TEXT",
        "ALTER TABLE mirrors ADD COLUMN visibility TEXT DEFAULT 'private'",
        "ALTER TABLE mirrors ADD COLUMN command TEXT",
        "ALTER TABLE mirrors ADD COLUMN slug TEXT",
        "ALTER TABLE mirrors ADD COLUMN is_worker INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE mirrors ADD COLUMN derivation_version INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    conn.execute("DROP INDEX IF EXISTS idx_mirrors_is_agent_spawn")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_is_worker ON mirrors(is_worker)")
    reconcile_worker_classification(conn)
    reconcile_derived_titles(conn)


def _rename_agent_spawn_column(conn: sqlite3.Connection) -> None:
    """Rename the legacy `is_agent_spawn` column to `is_worker`.

    The column always held one question — is this session a dispatched worker — but its
    original name asserted a wider one, that any agent-spawned session belonged in it.
    That conflation is what hid orchestrators from search, so the name is corrected
    rather than left to reintroduce the same reading.

    Raises on anything but the column already being absent, which is the normal state
    for a fresh database and for one already migrated.
    """
    try:
        conn.execute("ALTER TABLE mirrors RENAME COLUMN is_agent_spawn TO is_worker")
    except sqlite3.OperationalError as exc:
        if "no such column" not in str(exc).lower():
            raise


def reconcile_worker_classification(conn: sqlite3.Connection) -> None:
    """Realign stored `is_worker` with the current worker-command set.

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
        f"UPDATE mirrors SET is_worker = 0 "
        f"WHERE is_worker = 1 AND (command IS NULL OR command NOT IN ({placeholders}))",
        workers,
    )
    conn.execute(
        f"UPDATE mirrors SET is_worker = 1 WHERE is_worker = 0 AND command IN ({placeholders})",
        workers,
    )


def reconcile_derived_titles(conn: sqlite3.Connection) -> None:
    """Realign stored titles with the command each row records having been launched by.

    A row carrying a launch command owes that command's rendered title, so a stored row
    still holding text from an older derivation — a leaked doc heading, the raw command
    line — is stale and is rebuilt from the persisted `command` and `slug`.

    Only a command that names a real deployed artifact is trusted. Detection also fires
    on path fragments and prose, and those rows hold a genuine first-message title that
    rendering would replace with a humanized fragment; leaving them is the conservative
    side of an irreversible overwrite.

    Idempotent: a row already carrying its rendered title yields no update.
    """
    rows = conn.execute(
        "SELECT id, command, slug, title FROM mirrors WHERE command IS NOT NULL AND command <> ''"
    ).fetchall()
    updates: list[tuple[str, int]] = []
    for row_id, command, slug, title in rows:
        if not is_known_launch_command(command):
            continue
        rendered = render_title(command, slug)
        if rendered and rendered != title:
            updates.append((rendered, row_id))
    if updates:
        conn.executemany("UPDATE mirrors SET title = ? WHERE id = ?", updates)
