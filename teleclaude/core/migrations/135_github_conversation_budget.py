"""Create the fleet master's conversation request budget and the limit notices other computers owe it."""

from __future__ import annotations

import aiosqlite

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS github_conversation_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_github_conversation_sends_sent_at ON github_conversation_sends(sent_at);
CREATE TABLE IF NOT EXISTS github_conversation_budget (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pause_until TEXT,
    unnamed_limits INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS github_rate_limit_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    resume_at TEXT,
    delivered_at TEXT
);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Install the tables; they start empty and fill as the conversation runs."""
    await db.executescript(_CREATE_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
