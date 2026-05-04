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
    startup reconciliation can promote it to ``delivered_through_ts`` and skip
    redelivery of that exact range.
    """
    await db.executescript(
        """
        ALTER TABLE conversation_delivery_state
            ADD COLUMN pending_through_ts TEXT;
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite cannot drop columns reversibly here — no-op."""
