"""Tests for session_listeners — direct-link creation cursor-seeding contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core import session_listeners


def _make_link_row(link_id: str = "link-uuid") -> SimpleNamespace:
    return SimpleNamespace(
        link_id=link_id,
        mode="direct_link",
        status="active",
        created_by_session_id="caller",
        metadata_json=None,
        created_at="2026-05-08T12:00:00+00:00",
        updated_at="2026-05-08T12:00:00+00:00",
        closed_at=None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_or_reuse_direct_link_seeds_cursors_for_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NEW direct link must seed per-link delivery cursors for both
    directions at link creation time. Without this floor, the conversation
    projector falls back to the source session's stale global anchor and
    pulls pre-link transcript content into the first bundle."""
    new_link = _make_link_row()
    db = SimpleNamespace(
        get_active_links_between_sessions=AsyncMock(return_value=[]),
        create_conversation_link=AsyncMock(return_value=new_link),
        upsert_conversation_link_member=AsyncMock(),
        get_conversation_link=AsyncMock(return_value=new_link),
        upsert_conversation_delivery_state=AsyncMock(),
    )
    monkeypatch.setattr(session_listeners, "db", db)

    _, created = await session_listeners.create_or_reuse_direct_link(
        caller_session_id="caller",
        target_session_id="target",
        caller_name="Caller",
        target_name="Target",
        caller_computer="local",
        target_computer="local",
    )

    assert created is True
    assert db.upsert_conversation_delivery_state.await_count == 2
    seeded_pairs = {
        (
            kwargs["link_id"],
            kwargs["source_session_id"],
            kwargs["target_session_id"],
        )
        for kwargs in (
            db.upsert_conversation_delivery_state.await_args_list[0].kwargs,
            db.upsert_conversation_delivery_state.await_args_list[1].kwargs,
        )
    }
    assert seeded_pairs == {
        ("link-uuid", "caller", "target"),
        ("link-uuid", "target", "caller"),
    }
    # Each seed writes a non-null delivered_through_ts (the link-creation
    # floor). The exact value comes from datetime.now() — we assert it's
    # populated, not its literal value.
    for kwargs in db.upsert_conversation_delivery_state.await_args_list:
        assert kwargs.kwargs["delivered_through_ts"] is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_or_reuse_direct_link_does_not_reseed_existing_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reusing an existing active link must NOT re-seed cursors. The link's
    history (delivered_through_ts/pending_through_ts) belongs to that link
    and resetting it would lose the in-flight crash-recovery bound."""
    existing = _make_link_row()
    db = SimpleNamespace(
        get_active_links_between_sessions=AsyncMock(return_value=[existing]),
        sever_conversation_link=AsyncMock(),
        upsert_conversation_link_member=AsyncMock(),
        upsert_conversation_delivery_state=AsyncMock(),
    )
    monkeypatch.setattr(session_listeners, "db", db)

    _, created = await session_listeners.create_or_reuse_direct_link(
        caller_session_id="caller",
        target_session_id="target",
        caller_name="Caller",
        target_name="Target",
        caller_computer="local",
        target_computer="local",
    )

    assert created is False
    db.upsert_conversation_delivery_state.assert_not_awaited()
