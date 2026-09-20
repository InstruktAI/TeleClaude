"""Add durable Discord provider reflection state."""

from __future__ import annotations

import json
import re

import aiosqlite

_DISCORD_REFLECTION_STATE_SQL = """
CREATE TABLE IF NOT EXISTS discord_reflection_state (
    provider TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    provider_id INTEGER NOT NULL,
    parent_provider_id INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    verified_at TIMESTAMP,
    PRIMARY KEY (provider, logical_key)
);
CREATE INDEX IF NOT EXISTS idx_discord_reflection_scope
    ON discord_reflection_state (provider, scope_kind, scope_value);
"""
_LAUNCHER_SETTING_PATTERN = re.compile(r"^discord_launcher:(?P<forum_id>\d+):(?P<field>thread_id|message_id)$")
_SELECT_LAUNCHER_SETTINGS = "SELECT key, value FROM system_settings WHERE key LIKE 'discord_launcher:%'"
_UPSERT_LAUNCHER = """
INSERT INTO discord_reflection_state
    (provider, logical_key, artifact_kind, scope_kind, scope_value, provider_id, parent_provider_id, metadata_json)
VALUES (?, ?, 'forum_thread', 'project', ?, ?, ?, ?)
ON CONFLICT(provider, logical_key) DO NOTHING
"""
_DELETE_LAUNCHER_SETTINGS = "DELETE FROM system_settings WHERE key LIKE ?"


async def up(db: aiosqlite.Connection) -> None:
    """Install the forward-only Discord reflection-state table."""
    await db.executescript(_DISCORD_REFLECTION_STATE_SQL)  # guard: raw-sql
    cursor = await db.execute(_SELECT_LAUNCHER_SETTINGS)
    rows = await cursor.fetchall()
    launchers: dict[int, dict[str, int]] = {}
    for key, value in rows:
        match = _LAUNCHER_SETTING_PATTERN.match(str(key))
        if match is None:
            continue
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            continue
        forum_id = int(match.group("forum_id"))
        launchers.setdefault(forum_id, {})[match.group("field")] = parsed_value
    for forum_id, values in launchers.items():
        thread_id = values.get("thread_id")
        message_id = values.get("message_id")
        if thread_id is None or message_id is None:
            continue
        await db.execute(
            _UPSERT_LAUNCHER,
            (
                "discord",
                f"session_launcher:{forum_id}",
                str(forum_id),
                thread_id,
                forum_id,
                json.dumps({"message": message_id}),
            ),
        )
        await db.execute(_DELETE_LAUNCHER_SETTINGS, (f"discord_launcher:{forum_id}%",))
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted state migrates forward only."""
    _ = db
