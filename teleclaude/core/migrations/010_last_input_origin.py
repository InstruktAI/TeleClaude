"""Consolidate origin fields into last_input_origin."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Replace origin_adapter/last_input_adapter with last_input_origin."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns = [cast(str, row[1]) for row in rows]

    has_last_input_origin = "last_input_origin" in existing_columns
    has_legacy_origin = "origin_adapter" in existing_columns or "last_input_adapter" in existing_columns

    if has_last_input_origin and not has_legacy_origin:
        logger.info("last_input_origin already present; skipping migration")
        return

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

    select_expressions: list[str] = []
    for column in desired_columns:
        if column == "last_input_origin":
            if "last_input_origin" in existing_columns:
                expr = "last_input_origin"
            else:
                expr = "COALESCE(last_input_adapter, origin_adapter)"
        elif column in existing_columns:
            expr = column
        else:
            expr = "NULL"
        select_expressions.append(expr)

    column_list = ", ".join(desired_columns)
    select_list = ", ".join(select_expressions)
    await db.execute(f"INSERT INTO sessions_new ({column_list}) SELECT {select_list} FROM sessions")

    await db.execute("DROP TABLE sessions")
    await db.execute("ALTER TABLE sessions_new RENAME TO sessions")
    await db.commit()
    logger.info("Migrated origin fields to last_input_origin")
