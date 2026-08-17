"""Add durable reminder aggregates, source entries, and typed input fields."""

from __future__ import annotations

import aiosqlite

_INBOUND_NEW = "inbound_queue_reminder_migration"
_PARTS_NEW = "turn_authored_parts_reminder_migration"


async def _rebuild_inbound_queue(db: aiosqlite.Connection) -> None:
    await db.executescript(
        f"""
        CREATE TABLE {_INBOUND_NEW} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            origin TEXT NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'text'
                CHECK(message_type IN ('text', 'voice', 'file', 'reminder')),
            content TEXT NOT NULL DEFAULT '',
            payload_json TEXT,
            actor_id TEXT,
            actor_name TEXT,
            actor_avatar_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired')),
            created_at TEXT NOT NULL,
            processed_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            last_error TEXT,
            locked_at TEXT,
            source_message_id TEXT,
            source_channel_id TEXT,
            caller_session_id TEXT,
            caller_author_kind TEXT,
            caller_author_display TEXT,
            caller_agent_runtime TEXT,
            caller_thinking_mode TEXT,
            caller_machine_role TEXT,
            caller_job_role TEXT,
            caller_origin_prefix_len INTEGER,
            caller_origin_suffix_len INTEGER,
            binding_disposition TEXT
        );

        INSERT INTO {_INBOUND_NEW} (
            id, session_id, origin, message_type, content, payload_json,
            actor_id, actor_name, actor_avatar_url, status, created_at,
            processed_at, attempt_count, next_retry_at, last_error, locked_at,
            source_message_id, source_channel_id, caller_session_id,
            caller_author_kind, caller_author_display, caller_agent_runtime,
            caller_thinking_mode, caller_machine_role, caller_job_role,
            caller_origin_prefix_len, binding_disposition
        )
        SELECT
            id, session_id, origin, message_type, content, payload_json,
            actor_id, actor_name, actor_avatar_url, status, created_at,
            processed_at, attempt_count, next_retry_at, last_error, locked_at,
            source_message_id, source_channel_id, caller_session_id,
            caller_author_kind, caller_author_display, caller_agent_runtime,
            caller_thinking_mode, caller_machine_role, caller_job_role,
            caller_origin_prefix_len, binding_disposition
        FROM inbound_queue;

        DROP TABLE inbound_queue;
        ALTER TABLE {_INBOUND_NEW} RENAME TO inbound_queue;

        CREATE INDEX idx_inbound_queue_session_status
        ON inbound_queue(session_id, status, next_retry_at);
        CREATE UNIQUE INDEX idx_inbound_queue_source_dedup
        ON inbound_queue(origin, source_message_id)
        WHERE source_message_id IS NOT NULL;
        """
    )


async def _rebuild_turn_authored_parts(db: aiosqlite.Connection) -> None:
    await db.executescript(
        f"""
        CREATE TABLE {_PARTS_NEW} (
            binding_id TEXT NOT NULL,
            part_id INTEGER NOT NULL,
            part_kind TEXT NOT NULL
                CHECK(part_kind IN ('local', 'injected_peer', 'injected_reminder')),
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            original_source_session_id TEXT,
            author_kind TEXT NOT NULL CHECK(author_kind IN ('human', 'agent', 'machine')),
            author_display TEXT NOT NULL,
            author_agent_runtime TEXT,
            author_thinking_mode TEXT,
            author_machine_role TEXT,
            author_job_role TEXT,
            origin_surface TEXT,
            PRIMARY KEY (binding_id, part_id),
            FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
        );

        INSERT INTO {_PARTS_NEW} (
            binding_id, part_id, part_kind, span_start, span_end,
            original_source_session_id, author_kind, author_display,
            author_agent_runtime, author_thinking_mode, author_machine_role,
            author_job_role, origin_surface
        )
        SELECT
            binding_id, part_id, part_kind, span_start, span_end,
            original_source_session_id, author_kind, author_display,
            author_agent_runtime, author_thinking_mode, author_machine_role,
            author_job_role, origin_surface
        FROM turn_authored_parts;

        DROP TABLE turn_authored_parts;
        ALTER TABLE {_PARTS_NEW} RENAME TO turn_authored_parts;
        CREATE INDEX idx_turn_authored_parts_source
        ON turn_authored_parts(original_source_session_id);
        """
    )


async def up(db: aiosqlite.Connection) -> None:
    """Migrate owned state forward to the reminder-aware current schema."""
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await _rebuild_inbound_queue(db)
        await _rebuild_turn_authored_parts(db)
        async with db.execute("PRAGMA table_info(output_consumer_cursors)") as cursor:
            cursor_columns = {str(row[1]) for row in await cursor.fetchall()}
        if "last_reminder_entry_id" not in cursor_columns:
            await db.execute(
                "ALTER TABLE output_consumer_cursors ADD COLUMN last_reminder_entry_id INTEGER NOT NULL DEFAULT 0"
            )
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                session_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                profile TEXT,
                intent TEXT NOT NULL,
                trigger_type TEXT NOT NULL CHECK(trigger_type IN ('time', 'agent_event')),
                event_anchor TEXT,
                recurrence TEXT NOT NULL CHECK(recurrence IN ('one_shot', 'recurring')),
                interval_seconds REAL,
                armed_at TEXT NOT NULL,
                next_fire_at TEXT,
                generation INTEGER NOT NULL,
                occurrence_key TEXT NOT NULL,
                claimed_occurrence_key TEXT,
                claimed_at TEXT,
                PRIMARY KEY (session_id, slug)
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_next_fire
            ON reminders(next_fire_at) WHERE next_fire_at IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_reminders_event_anchor
            ON reminders(session_id, event_anchor) WHERE event_anchor IS NOT NULL;

            CREATE TABLE IF NOT EXISTS reminder_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                generation INTEGER NOT NULL,
                transition TEXT NOT NULL
                    CHECK(transition IN ('armed', 'replaced', 'cancelled', 'firing')),
                profile TEXT,
                intent TEXT NOT NULL,
                trigger_type TEXT NOT NULL CHECK(trigger_type IN ('time', 'agent_event')),
                event_anchor TEXT,
                recurrence TEXT NOT NULL CHECK(recurrence IN ('one_shot', 'recurring')),
                interval_seconds REAL,
                armed_at TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                next_fire_at TEXT,
                occurrence_key TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reminder_entries_session
            ON reminder_entries(session_id, entry_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reminder_entries_firing_occurrence
            ON reminder_entries(occurrence_key) WHERE transition = 'firing';
            """
        )
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
