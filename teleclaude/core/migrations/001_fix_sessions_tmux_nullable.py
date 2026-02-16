"""Fix sessions schema: allow NULL tmux_session_name and drop unique constraint."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration."""
    await db.execute("PRAGMA foreign_keys=OFF")
    await db.execute("BEGIN")
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions_new (
                session_id TEXT PRIMARY KEY,
                computer_name TEXT NOT NULL,
                title TEXT,
                tmux_session_name TEXT,
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
                last_output_raw TEXT,
                last_output_at TEXT,
                working_slug TEXT,
                lifecycle_status TEXT DEFAULT 'active',
                last_output_summary TEXT
            )
            """
        )
        await db.execute(
            """
            INSERT INTO sessions_new (
                session_id,
                computer_name,
                title,
                tmux_session_name,
                last_input_origin,
                adapter_metadata,
                created_at,
                last_activity,
                closed_at,
                terminal_size,
                project_path,
                subdir,
                description,
                initiated_by_ai,
                initiator_session_id,
                output_message_id,
                notification_sent,
                native_session_id,
                native_log_file,
                active_agent,
                thinking_mode,
                tui_log_file,
                tui_capture_started,
                last_message_sent,
                last_message_sent_at,
                last_output_raw,
                last_output_at,
                working_slug,
                lifecycle_status,
                last_output_summary
            )
            SELECT
                session_id,
                computer_name,
                title,
                tmux_session_name,
                last_input_origin,
                adapter_metadata,
                created_at,
                last_activity,
                closed_at,
                terminal_size,
                project_path,
                subdir,
                description,
                initiated_by_ai,
                initiator_session_id,
                output_message_id,
                notification_sent,
                native_session_id,
                native_log_file,
                active_agent,
                thinking_mode,
                tui_log_file,
                tui_capture_started,
                last_message_sent,
                last_message_sent_at,
                last_output_raw,
                last_output_at,
                working_slug,
                lifecycle_status,
                last_output_summary
            FROM sessions
            """
        )
        await db.execute("DROP TABLE sessions")
        await db.execute("ALTER TABLE sessions_new RENAME TO sessions")
        await db.execute(
            "UPDATE sessions SET tmux_session_name = NULL "
            "WHERE lifecycle_status = 'headless' OR tmux_session_name LIKE 'headless-%'"
        )
        await db.execute("COMMIT")
    except Exception:
        await db.execute("ROLLBACK")
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
