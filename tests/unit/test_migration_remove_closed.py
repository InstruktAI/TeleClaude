"""Tests for migration 004_remove_closed_column."""

import importlib

import aiosqlite
import pytest

migration = importlib.import_module("teleclaude.core.migrations.004_remove_closed_column")


@pytest.mark.asyncio
async def test_remove_closed_column_migrates_schema_and_data() -> None:
    """Migration should drop legacy closed column and preserve rows."""
    async with aiosqlite.connect(":memory:") as db:
        await db.execute(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                computer_name TEXT NOT NULL,
                title TEXT,
                tmux_session_name TEXT NOT NULL,
                origin_adapter TEXT NOT NULL DEFAULT 'telegram',
                adapter_metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                closed INTEGER DEFAULT 0,
                terminal_size TEXT DEFAULT '80x24',
                project_path TEXT DEFAULT '~',
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
                working_slug TEXT
            )
            """
        )
        await db.execute(
            """
            INSERT INTO sessions (session_id, computer_name, title, tmux_session_name, origin_adapter, closed)
            VALUES ('sess-1', 'TestMac', 'Test', 'tmux-1', 'rest', 0)
            """
        )
        await db.commit()

        await migration.up(db)

        cursor = await db.execute("PRAGMA table_info(sessions)")
        cols = [row[1] for row in await cursor.fetchall()]
        assert "closed" not in cols

        cursor = await db.execute("SELECT session_id, computer_name, title FROM sessions")
        row = await cursor.fetchone()
        assert row == ("sess-1", "TestMac", "Test")
