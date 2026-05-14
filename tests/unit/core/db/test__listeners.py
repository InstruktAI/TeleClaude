from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.core import db_models
from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_register_listener_returns_false_when_row_already_exists_and_updates_tmux_name(db: Db) -> None:
    inserted = await db.register_listener("target-1", "caller-1", "tmux-old")
    inserted_again = await db.register_listener("target-1", "caller-1", "tmux-new")
    listeners = await db.get_listeners_for_target("target-1")

    assert inserted is True
    assert inserted_again is False
    assert len(listeners) == 1
    assert listeners[0].caller_tmux_session == "tmux-new"


async def test_pop_listeners_for_target_returns_rows_and_clears_target(db: Db) -> None:
    await db.register_listener("target-1", "caller-1", "tmux-1")
    await db.register_listener("target-1", "caller-2", "tmux-2")

    popped = await db.pop_listeners_for_target("target-1")
    remaining = await db.get_listeners_for_target("target-1")

    assert {listener.caller_session_id for listener in popped} == {"caller-1", "caller-2"}
    assert remaining == []


async def test_cleanup_caller_listeners_and_count_only_remove_matching_caller(db: Db) -> None:
    await db.register_listener("target-1", "caller-1", "tmux-1")
    await db.register_listener("target-2", "caller-1", "tmux-1")
    await db.register_listener("target-3", "caller-2", "tmux-2")

    deleted = await db.cleanup_caller_listeners("caller-1")
    all_listeners = await db.get_all_listeners()
    count = await db.count_listeners()

    assert deleted == 2
    assert count == 1
    assert [(listener.target_session_id, listener.caller_session_id) for listener in all_listeners] == [
        ("target-3", "caller-2")
    ]


async def test_stale_listener_queries_reset_timestamps_without_removing_rows(db: Db) -> None:
    await db.register_listener("target-1", "caller-1", "tmux-1")
    stale_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    fresh_time = datetime.now(UTC).isoformat()

    async with db._session() as session:
        row = await session.get(
            db_models.SessionListenerRow,
            {"target_session_id": "target-1", "caller_session_id": "caller-1"},
        )
        assert row is not None
        row.registered_at = stale_time
        session.add(row)
        await session.commit()

    stale_targets = await db.get_stale_listener_targets(
        max_age_iso=(datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    )
    await db.reset_listener_timestamps("target-1", fresh_time)
    stale_after_reset = await db.get_stale_listener_targets(
        max_age_iso=(datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    )
    caller_rows = await db.get_listeners_for_caller("caller-1")

    assert stale_targets == ["target-1"]
    assert stale_after_reset == []
    assert [(listener.target_session_id, listener.registered_at) for listener in caller_rows] == [
        ("target-1", fresh_time)
    ]
