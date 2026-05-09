from __future__ import annotations

import importlib

import aiosqlite
import pytest

drop_session_metadata = importlib.import_module("teleclaude.core.migrations.045_drop_session_metadata_column")


@pytest.mark.asyncio
async def test_drop_session_metadata_column_removes_dead_blob_from_existing_sessions() -> None:
    db = await aiosqlite.connect(":memory:")
    try:
        await db.execute("""
            CREATE TABLE sessions (
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
                detached INTEGER NOT NULL DEFAULT 0,
                last_projected_at TEXT,
                last_projected_output_digest TEXT,
                turn_anchor_sha TEXT
            )
        """)
        await db.execute("""
            INSERT INTO sessions (
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
                lifecycle_status,
                detached,
                last_projected_at,
                last_projected_output_digest,
                turn_anchor_sha
            )
            VALUES (
                'sess-001',
                'builder-mac',
                'Prior Session',
                'tmux-001',
                'telegram',
                '{"adapter": true}',
                '{"dead": true}',
                '{"telegram": {"topic_id": 42}}',
                'worker',
                'builder',
                'active',
                1,
                '2026-05-01T12:00:00Z',
                'digest-001',
                'anchor-001'
            )
        """)
        await db.commit()

        await drop_session_metadata.up(db)

        async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
            rows = await cursor.fetchall()
        columns = {str(row[0]) for row in rows}
        async with db.execute("""
            SELECT
                session_id,
                adapter_metadata,
                origin_metadata,
                system_role,
                job,
                detached,
                last_projected_at,
                last_projected_output_digest,
                turn_anchor_sha
            FROM sessions
        """) as cursor:
            preserved = await cursor.fetchone()

        assert "session_metadata" not in columns
        assert preserved == (
            "sess-001",
            '{"adapter": true}',
            '{"telegram": {"topic_id": 42}}',
            "worker",
            "builder",
            1,
            "2026-05-01T12:00:00Z",
            "digest-001",
            "anchor-001",
        )
    finally:
        await db.close()
