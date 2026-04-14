from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_conversation_delivery_state_round_trips_and_updates_cursor(db: Db) -> None:
    initial_ts = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)
    later_ts = datetime(2026, 4, 14, 10, 5, 0, tzinfo=UTC)
    link = await db.create_conversation_link(mode="direct_link", created_by_session_id="source-001", metadata_json=None)

    await db.upsert_conversation_delivery_state(
        link_id=link.link_id,
        source_session_id="source-001",
        target_session_id="target-001",
        delivered_through_ts=initial_ts.isoformat(),
    )
    initial = await db.get_conversation_delivery_state(
        link_id=link.link_id,
        source_session_id="source-001",
        target_session_id="target-001",
    )

    await db.upsert_conversation_delivery_state(
        link_id=link.link_id,
        source_session_id="source-001",
        target_session_id="target-001",
        delivered_through_ts=later_ts.isoformat(),
    )
    updated = await db.get_conversation_delivery_state(
        link_id=link.link_id,
        source_session_id="source-001",
        target_session_id="target-001",
    )

    assert initial is not None
    assert initial.delivered_through_ts == initial_ts.isoformat()
    assert updated is not None
    assert updated.delivered_through_ts == later_ts.isoformat()
