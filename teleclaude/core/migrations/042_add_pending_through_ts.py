"""Add pending_through_ts to conversation_delivery_state for crash-safe bundle handoff."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the pending-handoff column.

    Bundled conversation delivery sends a single message covering multiple
    transcript segments. If the daemon crashes after the receiver accepts the
    bundle but before ``delivered_through_ts`` is advanced, naive replay would
    re-send a wider bundle (with newly arrived segments) under a different
    transport dedupe key — duplicating the already-delivered content. The
    pending column records the planned upper-bound BEFORE the send, so
    startup reconciliation can perform a **bounded replay**: rebuild the same
    range under the same dedupe key, re-send (receiver dedupes if it already
    accepted, or processes for the first time if the prior send did not reach
    the queue), and only after that handoff returns durably advance the cursor
    to the pending bound. Pending is never blindly promoted.
    """
    # Idempotent: skip if the column already exists. SQLite has no
    # ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` syntax, so we inspect
    # ``pragma_table_info`` first. This matters because ``schema.sql``
    # creates fresh databases with the column already present, while
    # upgraded databases need this migration to add it.
    cursor = await db.execute("PRAGMA table_info(conversation_delivery_state);")
    rows = await cursor.fetchall()
    await cursor.close()
    column_names = {row[1] for row in rows}
    if "pending_through_ts" not in column_names:
        await db.execute("ALTER TABLE conversation_delivery_state ADD COLUMN pending_through_ts TEXT;")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite cannot drop columns reversibly here — no-op."""
