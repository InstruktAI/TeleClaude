# pylint: disable=invalid-name,unused-argument,duplicate-code
"""Remove turn_triggered_by_linked_output from sessions."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild sessions without the dead linked-output boolean."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "turn_triggered_by_linked_output" not in columns:
        return

    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN")
        await db.execute("""
            CREATE TABLE sessions_new (
                session_id TEXT PRIMARY KEY,
                computer_name TEXT NOT NULL,
                title TEXT,
                tmux_session_name TEXT,
                last_input_origin TEXT NOT NULL DEFAULT 'telegram',
                adapter_metadata TEXT,
                session_metadata TEXT,
                origin_metadata TEXT,
                system_role TEXT,
                job TEXT,
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
                last_output_summary TEXT,
                last_output_digest TEXT,
                last_tool_done_at TEXT,
                last_tool_use_at TEXT,
                last_checkpoint_at TEXT,
                last_agent_stop_at TEXT,
                working_slug TEXT,
                lifecycle_status TEXT DEFAULT 'active',
                human_email TEXT,
                human_role TEXT,
                principal TEXT,
                last_memory_extraction_at TEXT,
                help_desk_processed_at TEXT,
                relay_status TEXT,
                relay_discord_channel_id TEXT,
                relay_started_at TEXT,
                char_offset INTEGER DEFAULT 0,
                transcript_files TEXT DEFAULT '[]',
                visibility TEXT DEFAULT 'private',
                detached INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            INSERT INTO sessions_new (
                session_id,
                computer_name,
                title,
                tmux_session_name,
                last_input_origin,
                adapter_metadata,
                session_metadata,
                origin_metadata,
                system_role,
                job,
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
                last_output_summary,
                last_output_digest,
                last_tool_done_at,
                last_tool_use_at,
                last_checkpoint_at,
                last_agent_stop_at,
                working_slug,
                lifecycle_status,
                human_email,
                human_role,
                principal,
                last_memory_extraction_at,
                help_desk_processed_at,
                relay_status,
                relay_discord_channel_id,
                relay_started_at,
                char_offset,
                transcript_files,
                visibility,
                detached
            )
            SELECT
                session_id,
                computer_name,
                title,
                tmux_session_name,
                last_input_origin,
                adapter_metadata,
                session_metadata,
                origin_metadata,
                system_role,
                job,
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
                last_output_summary,
                last_output_digest,
                last_tool_done_at,
                last_tool_use_at,
                last_checkpoint_at,
                last_agent_stop_at,
                working_slug,
                lifecycle_status,
                human_email,
                human_role,
                principal,
                last_memory_extraction_at,
                help_desk_processed_at,
                relay_status,
                relay_discord_channel_id,
                relay_started_at,
                char_offset,
                transcript_files,
                visibility,
                detached
            FROM sessions
        """)
        await db.execute("DROP TABLE sessions")
        await db.execute("ALTER TABLE sessions_new RENAME TO sessions")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_closed_at ON sessions(closed_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_initiator ON sessions(initiator_session_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_lifecycle_status ON sessions(lifecycle_status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_native_session_id ON sessions(native_session_id)")
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
