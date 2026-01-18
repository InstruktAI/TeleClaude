"""Add UX state columns to sessions table and migrate data from ux_state JSON."""

# mypy: disable-error-code="misc"
# Migration files handle untyped JSON data and sqlite rows

import json
from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migrations.constants import COLUMN_UX_STATE

logger = get_logger(__name__)

# Columns to add (name -> type definition)
REQUIRED_COLUMNS = {
    "output_message_id": "TEXT",
    "last_input_adapter": "TEXT",
    "notification_sent": "INTEGER DEFAULT 0",
    "native_session_id": "TEXT",
    "native_log_file": "TEXT",
    "active_agent": "TEXT",
    "thinking_mode": "TEXT",
    "tui_log_file": "TEXT",
    "tui_capture_started": "INTEGER DEFAULT 0",
    "last_message_sent": "TEXT",
    "last_message_sent_at": "TEXT",
    "last_feedback_received": "TEXT",
    "last_feedback_received_at": "TEXT",
}


async def up(db: aiosqlite.Connection) -> None:
    """Add UX columns and migrate data from ux_state JSON blob."""
    # Get current columns
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns: set[str] = set()
    for row in rows:
        col_name = cast(str, row[1])
        existing_columns.add(col_name)

    # Add missing columns
    added_columns: list[str] = []
    for column_name, column_type in REQUIRED_COLUMNS.items():
        if column_name not in existing_columns:
            await db.execute(f"ALTER TABLE sessions ADD COLUMN {column_name} {column_type}")
            added_columns.append(column_name)

    if added_columns:
        await db.commit()
        logger.info("Added columns: %s", ", ".join(added_columns))

    # Migrate data from ux_state JSON if column exists
    if COLUMN_UX_STATE in existing_columns:
        await _migrate_ux_state_data(db)


async def _migrate_ux_state_data(db: aiosqlite.Connection) -> None:
    """Migrate data from ux_state JSON blob to individual columns."""
    cursor = await db.execute("SELECT session_id, ux_state FROM sessions WHERE ux_state IS NOT NULL")
    rows = await cursor.fetchall()

    migrated_count = 0
    for row in rows:
        session_id = row[0]
        ux_state_raw = row[1]

        if not ux_state_raw:
            continue

        try:
            ux = json.loads(ux_state_raw)
        except json.JSONDecodeError as e:
            logger.warning("Skipping session %s - invalid ux_state JSON: %s", session_id, e)
            continue

        # Update scalar columns
        await db.execute(
            """
            UPDATE sessions SET
                output_message_id = ?,
                last_input_adapter = ?,
                notification_sent = ?,
                native_session_id = ?,
                native_log_file = ?,
                active_agent = ?,
                thinking_mode = ?,
                tui_log_file = ?,
                tui_capture_started = ?
            WHERE session_id = ?
            """,
            (
                ux.get("output_message_id"),
                ux.get("last_input_adapter"),
                1 if ux.get("notification_sent") else 0,
                ux.get("native_session_id"),
                ux.get("native_log_file"),
                ux.get("active_agent"),
                ux.get("thinking_mode"),
                ux.get("tui_log_file"),
                1 if ux.get("tui_capture_started") else 0,
                session_id,
            ),
        )

        # Migrate pending_deletions list
        for msg_id in ux.get("pending_deletions", []):
            await db.execute(
                """
                INSERT OR IGNORE INTO pending_message_deletions
                    (session_id, message_id, deletion_type)
                VALUES (?, ?, 'user_input')
                """,
                (session_id, msg_id),
            )

        # Migrate pending_feedback_deletions list
        for msg_id in ux.get("pending_feedback_deletions", []):
            await db.execute(
                """
                INSERT OR IGNORE INTO pending_message_deletions
                    (session_id, message_id, deletion_type)
                VALUES (?, ?, 'feedback')
                """,
                (session_id, msg_id),
            )

        migrated_count += 1

    await db.commit()
    if migrated_count > 0:
        logger.info("Migrated ux_state data for %d sessions", migrated_count)
