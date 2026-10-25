"""Cancel every live ``integrator-queue-watch`` reminder, because the parked integrator now wakes only on events.

The profile is retired from the prescribed registry, so a stored aggregate that still names it could no longer be
read. Each live aggregate is removed the way a cancellation removes it: a ``cancelled`` entry carrying the
aggregate's recorded values is appended to the lifecycle log beside the removal, so the audit trail keeps every
retired reminder. See ``local/projects/teleclaude/spec/feature/workflow/integration-state-machine``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_RETIRED_PROFILE: Final = "integrator-queue-watch"
_CANCELLED_TRANSITION: Final = "cancelled"
_APPEND_CANCELLATION_SQL: Final = """
INSERT INTO reminder_entries (
    session_id, slug, generation, transition, profile, intent, trigger_type, event_anchor, recurrence,
    interval_seconds, armed_at, occurred_at, next_fire_at, occurrence_key, sliding, firing_number
)
SELECT
    session_id, slug, generation, ?, profile, intent, trigger_type, event_anchor, recurrence,
    interval_seconds, armed_at, ?, next_fire_at, occurrence_key, sliding, NULL
FROM reminders
WHERE profile = ?
"""
_REMOVE_AGGREGATES_SQL: Final = "DELETE FROM reminders WHERE profile = ?"
_CANCELLED_EVENT: Final = "integrator_queue_watch_reminders_cancelled"


async def up(db: aiosqlite.Connection) -> None:
    """Append a cancellation entry for each live queue-watch aggregate and remove the aggregates, together."""
    occurred_at = datetime.now(UTC).isoformat()
    await db.execute(_APPEND_CANCELLATION_SQL, (_CANCELLED_TRANSITION, occurred_at, _RETIRED_PROFILE))
    removed = await db.execute(_REMOVE_AGGREGATES_SQL, (_RETIRED_PROFILE,))
    await db.commit()
    logger.info(_CANCELLED_EVENT, cancelled_count=removed.rowcount)
