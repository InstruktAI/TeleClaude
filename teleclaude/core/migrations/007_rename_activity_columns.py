"""Rename activity tracking columns: after_model/agent_output → tool_use/tool_done."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Rename last_after_model_at → last_tool_use_at and last_agent_output_at → last_tool_done_at."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "last_after_model_at" in column_names and "last_tool_use_at" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_after_model_at TO last_tool_use_at")

    if "last_agent_output_at" in column_names and "last_tool_done_at" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_agent_output_at TO last_tool_done_at")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert column renames."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "last_tool_use_at" in column_names and "last_after_model_at" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_tool_use_at TO last_after_model_at")

    if "last_tool_done_at" in column_names and "last_agent_output_at" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_tool_done_at TO last_agent_output_at")

    await db.commit()
