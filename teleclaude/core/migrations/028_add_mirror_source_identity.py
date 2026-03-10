"""Add source_identity to mirrors and rebuild uniqueness around canonical transcript identity."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript_discovery import build_source_identity


async def _table_columns(db: aiosqlite.Connection, table: str) -> list[str]:
    rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
    return [str(row[1]) for row in rows]


def _source_identity_for_row(agent_value: str, metadata_raw: str | None) -> str | None:
    try:
        metadata = json.loads(metadata_raw or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict):
        return None
    transcript_path = metadata.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    try:
        agent = AgentName(agent_value)
    except ValueError:
        return None
    return build_source_identity(Path(transcript_path), agent)


async def _create_mirrors_with_source_identity(db: aiosqlite.Connection) -> None:
    await db.execute("DROP TABLE IF EXISTS mirrors_new")
    await db.execute(
        """
        CREATE TABLE mirrors_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            source_identity TEXT,
            computer TEXT NOT NULL,
            agent TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            timestamp_start TEXT,
            timestamp_end TEXT,
            conversation_text TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


async def _create_legacy_mirrors_table(db: aiosqlite.Connection) -> None:
    await db.execute("DROP TABLE IF EXISTS mirrors_new")
    await db.execute(
        """
        CREATE TABLE mirrors_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            computer TEXT NOT NULL,
            agent TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            timestamp_start TEXT,
            timestamp_end TEXT,
            conversation_text TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


async def _recreate_indexes_and_fts(db: aiosqlite.Connection, *, include_source_identity: bool) -> None:
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_project ON mirrors(project)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC)")
    if include_source_identity:
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mirrors_source_identity ON mirrors(source_identity)")
    await db.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS mirrors_fts USING fts5(
            title,
            conversation_text,
            content='mirrors',
            content_rowid='id'
        )
        """
    )
    await db.execute(
        """
        INSERT INTO mirrors_fts(rowid, title, conversation_text)
        SELECT id, title, conversation_text FROM mirrors
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS mirrors_ai AFTER INSERT ON mirrors BEGIN
            INSERT INTO mirrors_fts(rowid, title, conversation_text)
            VALUES (new.id, new.title, new.conversation_text);
        END
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS mirrors_ad AFTER DELETE ON mirrors BEGIN
            INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
            VALUES ('delete', old.id, old.title, old.conversation_text);
        END
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS mirrors_au AFTER UPDATE ON mirrors BEGIN
            INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
            VALUES ('delete', old.id, old.title, old.conversation_text);
            INSERT INTO mirrors_fts(rowid, title, conversation_text)
            VALUES (new.id, new.title, new.conversation_text);
        END
        """
    )


async def _drop_mirror_indexes_and_fts(db: aiosqlite.Connection) -> None:
    await db.execute("DROP TRIGGER IF EXISTS mirrors_au")
    await db.execute("DROP TRIGGER IF EXISTS mirrors_ad")
    await db.execute("DROP TRIGGER IF EXISTS mirrors_ai")
    await db.execute("DROP TABLE IF EXISTS mirrors_fts")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_source_identity")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_timestamp")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_project")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_agent")


async def up(db: aiosqlite.Connection) -> None:
    """Add source_identity and rebuild the mirrors table."""
    try:
        columns = await _table_columns(db, "mirrors")
    except aiosqlite.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return
        raise
    if "source_identity" in columns:
        return

    rows = await (
        await db.execute(
            """
            SELECT
                id,
                session_id,
                computer,
                agent,
                project,
                title,
                timestamp_start,
                timestamp_end,
                conversation_text,
                message_count,
                metadata,
                created_at,
                updated_at
            FROM mirrors
            ORDER BY id
            """
        )
    ).fetchall()
    payloads = [
        (
            row[0],
            row[1],
            _source_identity_for_row(str(row[3]), row[10]),
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            row[9],
            row[10],
            row[11],
            row[12],
        )
        for row in rows
    ]

    await _create_mirrors_with_source_identity(db)
    await db.executemany(
        """
        INSERT INTO mirrors_new (
            id,
            session_id,
            source_identity,
            computer,
            agent,
            project,
            title,
            timestamp_start,
            timestamp_end,
            conversation_text,
            message_count,
            metadata,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payloads,
    )
    # Deduplicate: keep most recent row per source_identity, NULL the rest.
    # SQLite allows multiple NULLs in a UNIQUE index.
    await db.execute(
        """
        UPDATE mirrors_new
        SET source_identity = NULL
        WHERE source_identity IS NOT NULL
          AND id NOT IN (
              SELECT MAX(id) FROM mirrors_new
              WHERE source_identity IS NOT NULL
              GROUP BY source_identity
          )
        """
    )

    await _drop_mirror_indexes_and_fts(db)
    await db.execute("DROP TABLE mirrors")
    await db.execute("ALTER TABLE mirrors_new RENAME TO mirrors")
    await _recreate_indexes_and_fts(db, include_source_identity=True)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop source_identity and restore session_id uniqueness."""
    try:
        columns = await _table_columns(db, "mirrors")
    except aiosqlite.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return
        raise
    if "source_identity" not in columns:
        return

    rows = await (
        await db.execute(
            """
            SELECT
                id,
                session_id,
                computer,
                agent,
                project,
                title,
                timestamp_start,
                timestamp_end,
                conversation_text,
                message_count,
                metadata,
                created_at,
                updated_at
            FROM mirrors
            ORDER BY updated_at DESC, id DESC
            """
        )
    ).fetchall()
    payloads: list[tuple[object, ...]] = []
    seen_session_ids: set[str] = set()
    for row in rows:
        session_id = str(row[1])
        if session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        payloads.append(tuple(row))

    await _create_legacy_mirrors_table(db)
    await db.executemany(
        """
        INSERT INTO mirrors_new (
            id,
            session_id,
            computer,
            agent,
            project,
            title,
            timestamp_start,
            timestamp_end,
            conversation_text,
            message_count,
            metadata,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payloads,
    )
    await _drop_mirror_indexes_and_fts(db)
    await db.execute("DROP TABLE mirrors")
    await db.execute("ALTER TABLE mirrors_new RENAME TO mirrors")
    await _recreate_indexes_and_fts(db, include_source_identity=False)
    await db.commit()
