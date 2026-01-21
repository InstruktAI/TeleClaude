"""Remove legacy closed column from sessions table."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migrations.constants import COLUMN_CLOSED

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Drop the legacy closed column from sessions table if present."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns = [cast(str, row[1]) for row in rows]

    if COLUMN_CLOSED not in existing_columns:
        logger.info("Legacy closed column not present; skipping migration")
        return

    # Desired schema (matches core/schema.sql)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions_new (
            session_id TEXT PRIMARY KEY,
            computer_name TEXT NOT NULL,
            title TEXT,
            tmux_session_name TEXT NOT NULL,
            last_input_origin TEXT NOT NULL DEFAULT 'telegram',
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

    desired_columns = [
        "session_id",
        "computer_name",
        "title",
        "tmux_session_name",
        "last_input_origin",
        "adapter_metadata",
        "created_at",
        "last_activity",
        "closed_at",
        "terminal_size",
        "project_path",
        "subdir",
        "description",
        "initiated_by_ai",
        "initiator_session_id",
        "output_message_id",
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

    insert_columns = [col for col in desired_columns if col in existing_columns]
    column_list = ", ".join(insert_columns)
    await db.execute(f"INSERT INTO sessions_new ({column_list}) SELECT {column_list} FROM sessions")

    await db.execute("DROP TABLE sessions")
    await db.execute("ALTER TABLE sessions_new RENAME TO sessions")
    await db.commit()
    logger.info("Removed legacy closed column from sessions table")
