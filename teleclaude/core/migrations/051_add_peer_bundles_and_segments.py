"""Add durable structured peer bundle and segment tables.

Replaces the text-parsed bridge grammar with a durable, structured carrier:
one bundle per accepted peer delivery, with ordered segments each carrying an
immutable author snapshot taken at write time so historical attribution
survives the source session's own fields changing or the session itself
disappearing later.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create the peer bundle and segment tables."""
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS peer_bundles (
            bundle_key TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            source_session_id TEXT NOT NULL,
            target_session_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_peer_bundles_target
        ON peer_bundles(target_session_id);

        CREATE INDEX IF NOT EXISTS idx_peer_bundles_source_target
        ON peer_bundles(source_session_id, target_session_id);

        CREATE TABLE IF NOT EXISTS peer_bundle_segments (
            bundle_key TEXT NOT NULL,
            segment_id INTEGER NOT NULL,
            original_source_session_id TEXT NOT NULL,
            author_kind TEXT NOT NULL CHECK(author_kind IN ('human', 'agent', 'machine')),
            author_display TEXT NOT NULL,
            author_agent_runtime TEXT,
            author_thinking_mode TEXT,
            author_machine_role TEXT,
            author_job_role TEXT,
            occurred_at TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (bundle_key, segment_id),
            FOREIGN KEY (bundle_key) REFERENCES peer_bundles(bundle_key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_peer_bundle_segments_source
        ON peer_bundle_segments(original_source_session_id);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
