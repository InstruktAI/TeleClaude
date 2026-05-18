"""Tests for session_listeners — direct-link cursor seeding and notification suppression."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core import session_listeners
from teleclaude.core.session_listeners import SessionListener


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


def _make_listener(
    *,
    caller_session_id: str,
    target_session_id: str = "target",
    caller_tmux_session: str = "tc_caller",
    one_shot: bool = False,
) -> SessionListener:
    return SessionListener(
        target_session_id=target_session_id,
        caller_session_id=caller_session_id,
        caller_tmux_session=caller_tmux_session,
        registered_at=datetime.now(UTC),
        one_shot=one_shot,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_listeners_suppresses_when_active_direct_link_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a caller holds an active direct link with the target, listener
    notifications to that caller are skipped. The link's cross-delivery
    channel supersedes passive notification for the duration of the link."""
    listener = _make_listener(caller_session_id="caller-with-link", one_shot=False)
    active_link = _make_link_row(link_id="link-active")
    db = SimpleNamespace(
        get_active_link_between_sessions=AsyncMock(return_value=active_link),
        unregister_listener=AsyncMock(),
    )
    monkeypatch.setattr(session_listeners, "db", db)
    monkeypatch.setattr(
        session_listeners,
        "get_listeners",
        AsyncMock(return_value=[listener]),
    )
    deliver_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(session_listeners, "deliver_listener_message", deliver_mock)

    delivered = await session_listeners._notify_listeners("target", "system message")

    assert delivered == 0
    deliver_mock.assert_not_awaited()
    db.unregister_listener.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_listeners_delivers_when_no_active_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an active direct link the listener receives the notification."""
    listener = _make_listener(caller_session_id="caller-no-link", one_shot=False)
    db = SimpleNamespace(
        get_active_link_between_sessions=AsyncMock(return_value=None),
        unregister_listener=AsyncMock(),
    )
    monkeypatch.setattr(session_listeners, "db", db)
    monkeypatch.setattr(
        session_listeners,
        "get_listeners",
        AsyncMock(return_value=[listener]),
    )
    deliver_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(session_listeners, "deliver_listener_message", deliver_mock)

    delivered = await session_listeners._notify_listeners("target", "system message")

    assert delivered == 1
    deliver_mock.assert_awaited_once()
    db.unregister_listener.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_listeners_suppression_is_per_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the caller with an active link is suppressed; other listeners deliver normally."""
    linked_caller = _make_listener(caller_session_id="caller-linked", one_shot=False)
    other_caller = _make_listener(
        caller_session_id="caller-passive",
        caller_tmux_session="tc_passive",
        one_shot=False,
    )
    active_link = _make_link_row(link_id="link-linked-only")

    async def get_link_for_pair(a: str, b: str, *, mode: str | None = None) -> object:
        del b, mode
        if a == "caller-linked":
            return active_link
        return None

    db = SimpleNamespace(
        get_active_link_between_sessions=AsyncMock(side_effect=get_link_for_pair),
        unregister_listener=AsyncMock(),
    )
    monkeypatch.setattr(session_listeners, "db", db)
    monkeypatch.setattr(
        session_listeners,
        "get_listeners",
        AsyncMock(return_value=[linked_caller, other_caller]),
    )
    deliver_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(session_listeners, "deliver_listener_message", deliver_mock)

    delivered = await session_listeners._notify_listeners("target", "system message")

    assert delivered == 1
    deliver_mock.assert_awaited_once_with(
        "caller-passive",
        "tc_passive",
        "system message",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_listeners_suppression_preserves_one_shot_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-shot listener that gets suppressed must NOT be removed — its
    delivery never happened, so the row persists for the next event."""
    listener = _make_listener(caller_session_id="caller-with-link", one_shot=True)
    active_link = _make_link_row(link_id="link-active")
    db = SimpleNamespace(
        get_active_link_between_sessions=AsyncMock(return_value=active_link),
        unregister_listener=AsyncMock(),
    )
    monkeypatch.setattr(session_listeners, "db", db)
    monkeypatch.setattr(
        session_listeners,
        "get_listeners",
        AsyncMock(return_value=[listener]),
    )
    monkeypatch.setattr(
        session_listeners,
        "deliver_listener_message",
        AsyncMock(return_value=True),
    )

    delivered = await session_listeners._notify_listeners("target", "system message")

    assert delivered == 0
    db.unregister_listener.assert_not_awaited()
