"""Rename feedback columns to output_summary for vocabulary unification.

last_feedback_received    → last_output_raw
last_feedback_received_at → last_output_at
last_feedback_summary     → last_output_summary
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Rename feedback columns to output_summary vocabulary."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "last_feedback_received" in column_names and "last_output_raw" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_feedback_received TO last_output_raw")

    if "last_feedback_received_at" in column_names and "last_output_at" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_feedback_received_at TO last_output_at")

    if "last_feedback_summary" in column_names and "last_output_summary" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_feedback_summary TO last_output_summary")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert column renames."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "last_output_raw" in column_names and "last_feedback_received" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_output_raw TO last_feedback_received")

    if "last_output_at" in column_names and "last_feedback_received_at" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_output_at TO last_feedback_received_at")

    if "last_output_summary" in column_names and "last_feedback_summary" not in column_names:
        await db.execute("ALTER TABLE sessions RENAME COLUMN last_output_summary TO last_feedback_summary")

    await db.commit()
