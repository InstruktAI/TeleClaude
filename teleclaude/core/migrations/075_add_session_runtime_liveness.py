"""Add authoritative runtime-liveness facts and demote unproved active sessions."""

from __future__ import annotations

import aiosqlite

from teleclaude.core.session_lifecycle import LifecycleTransitionReason


async def up(db: aiosqlite.Connection) -> None:
    """Migrate owned session rows to the current lifecycle contract."""
    for column in (
        "runtime_start_observed INTEGER DEFAULT 0",
        "runtime_activity_at TEXT",
        "lifecycle_transitioned_at TEXT",
        "lifecycle_transition_reason TEXT",
    ):
        await db.execute(f"ALTER TABLE sessions ADD COLUMN {column}")  # guard: static migration declaration
    await db.execute(
        "UPDATE sessions SET runtime_start_observed = 1, "
        "runtime_activity_at = COALESCE(last_agent_stop_at, last_agent_idle_at, last_output_at, last_message_sent_at), "
        f"lifecycle_transition_reason = '{LifecycleTransitionReason.MIGRATED_NATIVE_SESSION.value}' "
        "WHERE lifecycle_status = 'active' AND active_agent IS NOT NULL AND native_session_id IS NOT NULL"
    )
    await db.execute(
        "UPDATE sessions SET lifecycle_status = 'initializing', lifecycle_transition_reason = 'migrated_unproven', "
        "lifecycle_transitioned_at = CURRENT_TIMESTAMP "
        "WHERE lifecycle_status = 'active' AND active_agent IS NOT NULL AND native_session_id IS NULL"
    )
    await db.commit()
