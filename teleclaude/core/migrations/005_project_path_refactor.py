"""Add project_path and subdir columns and remove legacy working_directory."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild sessions table to use project_path/subdir and drop working_directory."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns = [cast(str, row[1]) for row in rows]

    # If working_directory is already gone and project_path exists, we're done
    if "working_directory" not in existing_columns and "project_path" in existing_columns:
        logger.info("Sessions table already refactored; skipping migration")
        return

    # Create new table with desired schema
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions_new (
            session_id TEXT PRIMARY KEY,
            computer_name TEXT NOT NULL,
            title TEXT,
            tmux_session_name TEXT NOT NULL,
            origin_adapter TEXT NOT NULL DEFAULT 'telegram',
            adapter_metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            terminal_size TEXT DEFAULT '80x24',
            project_path TEXT,
            subdir TEXT,
            description TEXT,
            initiated_by_ai BOOLEAN DEFAULT 0,
            initiator_session_id TEXT,
            output_message_id TEXT,
            last_input_adapter TEXT,
            notification_sent INTEGER DEFAULT 0,
            native_session_id TEXT,
            native_log_file TEXT,
            active_agent TEXT,
            thinking_mode TEXT,
            tui_log_file TEXT,
            tui_capture_started INTEGER DEFAULT 0,
            last_message_sent TEXT,
            last_message_sent_at TEXT,
            last_feedback_received TEXT,
            last_feedback_received_at TEXT,
            working_slug TEXT,
            UNIQUE(computer_name, tmux_session_name)
        )
        """
    )

    # Define columns to copy directly (present in both old and new schemas)
    desired_columns = [
        "session_id",
        "computer_name",
        "title",
        "tmux_session_name",
        "origin_adapter",
        "adapter_metadata",
        "created_at",
        "last_activity",
        "closed_at",
        "terminal_size",
        "description",
        "initiated_by_ai",
        "initiator_session_id",
        "output_message_id",
        "last_input_adapter",
        "notification_sent",
        "native_session_id",
        "native_log_file",
        "active_agent",
        "thinking_mode",
        "tui_log_file",
        "tui_capture_started",
        "last_message_sent",
        "last_message_sent_at",
        "last_feedback_received",
        "last_feedback_received_at",
        "working_slug",
    ]

    common_columns = [col for col in desired_columns if col in existing_columns]

    # We also want to backfill project_path from working_directory if it exists
    if "working_directory" in existing_columns:
        # Initial copy of common columns
        cols_str = ", ".join(common_columns)
        await db.execute(f"INSERT INTO sessions_new ({cols_str}) SELECT {cols_str} FROM sessions")

        # Backfill project_path from working_directory
        await db.execute(
            "UPDATE sessions_new SET project_path = (SELECT working_directory FROM sessions WHERE sessions.session_id = sessions_new.session_id)"
        )
        logger.info("Backfilled project_path from legacy working_directory")
    else:
        # Just copy common columns (including project_path/subdir if they already existed)
        if "project_path" in existing_columns:
            common_columns.append("project_path")
        if "subdir" in existing_columns:
            common_columns.append("subdir")

        cols_str = ", ".join(common_columns)
        await db.execute(f"INSERT INTO sessions_new ({cols_str}) SELECT {cols_str} FROM sessions")

    await db.execute("DROP TABLE sessions")
    await db.execute("ALTER TABLE sessions_new RENAME TO sessions")
    await db.commit()
    logger.info("Sessions table refactored: removed working_directory, ensured project_path/subdir")
