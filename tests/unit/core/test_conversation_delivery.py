from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core import conversation_delivery
from teleclaude.core.conversation_delivery import (
    ConversationSegment,
    deliver_pending_conversation_updates,
    reconcile_outstanding_conversation_deliveries,
    schedule_debounced_delivery,
)
from teleclaude.core.conversation_messages import (
    format_peer_message,
    is_conversation_bridge_message,
)
from teleclaude.core.models import Session

# Per-link cursor anchored at link creation; tests use a fixed floor.
_LINK_FLOOR = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)
_LINK_FLOOR_ISO = _LINK_FLOOR.isoformat()


def _session(**kwargs: object) -> Session:
    defaults = {
        "session_id": "source-001",
        "computer_name": "local",
        "tmux_session_name": "tc-source-001",
        "title": "Source Session",
        "active_agent": "claude",
        "native_log_file": "/tmp/source.jsonl",
    }
    defaults.update(kwargs)
    return Session(**defaults)


def _persisted_at_floor() -> SimpleNamespace:
    """Persisted delivery state with cursor at link-creation floor, no pending."""
    return SimpleNamespace(delivered_through_ts=_LINK_FLOOR_ISO, pending_through_ts=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_bundles_mixed_segments_into_one_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed user+assistant segments since the cursor must produce ONE bundled
    process_message call whose body contains BOTH inner markers in temporal
    order, and the cursor must advance once to the latest segment timestamp.
    """
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=_persisted_at_floor()),
        upsert_conversation_delivery_state=AsyncMock(),
    )
    collect_segments = AsyncMock(
        return_value=[
            ConversationSegment(
                role="user",
                text="Please inspect the changed API contract.",
                timestamp=datetime(2026, 4, 14, 10, 1, 0, tzinfo=UTC),
            ),
            ConversationSegment(
                role="assistant",
                text="I narrowed the regression to the linked replay path.",
                timestamp=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC),
            ),
        ]
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since", collect_segments
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 1
    assert command_service.process_message.await_count == 1
    sole_call = command_service.process_message.await_args_list[0].args[0]
    assert sole_call.source_message_id is not None
    assert sole_call.text.startswith("[TeleClaude - Peer ")
    user_marker_idx = sole_call.text.find("--- Human @")
    assistant_marker_idx = sole_call.text.find("--- Agent @")
    assert user_marker_idx != -1
    assert assistant_marker_idx != -1
    assert user_marker_idx < assistant_marker_idx
    assert "Please inspect the changed API contract." in sole_call.text
    assert "I narrowed the regression to the linked replay path." in sole_call.text
    # Two upserts per delivery: pre-pending (planned upper bound, before send),
    # then clear-pending+advance (delivered timestamp, after send).
    assert db.upsert_conversation_delivery_state.await_count == 2
    pre_call = db.upsert_conversation_delivery_state.await_args_list[0].kwargs
    advance_call = db.upsert_conversation_delivery_state.await_args_list[1].kwargs
    assert pre_call == {
        "link_id": "link-001",
        "source_session_id": "source-001",
        "target_session_id": "target-001",
        "delivered_through_ts": _LINK_FLOOR_ISO,
        "pending_through_ts": datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat(),
    }
    assert advance_call == {
        "link_id": "link-001",
        "source_session_id": "source-001",
        "target_session_id": "target-001",
        "delivered_through_ts": datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat(),
        "pending_through_ts": None,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_does_not_advance_cursor_when_delivery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock(side_effect=RuntimeError("delivery failed")))
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=_persisted_at_floor()),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(
            return_value=[
                ConversationSegment(
                    role="assistant",
                    text="The replay still needs a persisted cursor.",
                    timestamp=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC),
                )
            ]
        ),
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 0
    # Pre-pending write happens before send; advance write must not happen.
    assert db.upsert_conversation_delivery_state.await_count == 1
    pre_call = db.upsert_conversation_delivery_state.await_args_list[0].kwargs
    assert pre_call["delivered_through_ts"] == _LINK_FLOOR_ISO
    assert pre_call["pending_through_ts"] == datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconcile_outstanding_conversation_deliveries_replays_local_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _session(session_id="source-001", computer_name="local")
    db = SimpleNamespace(list_sessions=AsyncMock(return_value=[source]))
    deliver = AsyncMock(return_value=2)

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr("teleclaude.core.conversation_delivery.deliver_pending_conversation_updates", deliver)

    repaired = await reconcile_outstanding_conversation_deliveries(
        "local",
        client=MagicMock(),
        command_service=MagicMock(),
    )

    assert repaired == 2
    deliver.assert_awaited_once()


@pytest.mark.unit
def test_format_peer_message_orders_markers_chronologically() -> None:
    """Bundled body wraps the whole delta in one outer header and emits one
    inner marker per segment in temporal order, with role-specific labels."""
    body = format_peer_message(
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[
            ("user", datetime(2026, 5, 4, 9, 50, 10, tzinfo=UTC), "tail your pair"),
            ("assistant", datetime(2026, 5, 4, 9, 51, 42, tzinfo=UTC), "checking now"),
            ("assistant", datetime(2026, 5, 4, 9, 52, 18, tzinfo=UTC), "found the issue"),
        ],
    )
    assert body.startswith("[TeleClaude - Peer (sess-a) on MozBook]")
    user_idx = body.find("--- Human @ 2026-05-04T09:50:10")
    first_assistant_idx = body.find("--- Agent @ 2026-05-04T09:51:42")
    second_assistant_idx = body.find("--- Agent @ 2026-05-04T09:52:18")
    assert -1 < user_idx < first_assistant_idx < second_assistant_idx
    assert "tail your pair" in body
    assert "checking now" in body
    assert "found the issue" in body


@pytest.mark.unit
def test_format_peer_message_handles_missing_timestamp() -> None:
    body = format_peer_message(
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[("assistant", None, "no timestamp")],
    )
    assert "--- Agent @ unknown ---" in body
    assert "no timestamp" in body


@pytest.mark.unit
def test_format_peer_message_empty_segments_returns_empty_string() -> None:
    body = format_peer_message(
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[],
    )
    assert body == ""


@pytest.mark.unit
def test_is_conversation_bridge_message_recognizes_peer_prefix() -> None:
    """The peer prefix must be recognized as a bridge message so the inbound
    message handler treats it as machine-originated content."""
    body = format_peer_message(
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[("assistant", datetime(2026, 5, 4, 9, 50, 10, tzinfo=UTC), "x")],
    )
    assert is_conversation_bridge_message(body)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_debounced_delivery_coalesces_rapid_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three rapid agent_stops within the debounce window collapse into ONE
    delivery; the timer resets on each new signal and only fires after the
    latest signal is followed by quiet."""
    monkeypatch.setattr("teleclaude.core.conversation_delivery._DEBOUNCE_WINDOW_S", 0.05)
    deliver = AsyncMock(return_value=1)
    monkeypatch.setattr("teleclaude.core.conversation_delivery.deliver_pending_conversation_updates", deliver)

    client = MagicMock()
    schedule_debounced_delivery("source-debounce", client=client)
    await asyncio.sleep(0.01)
    schedule_debounced_delivery("source-debounce", client=client)
    await asyncio.sleep(0.01)
    schedule_debounced_delivery("source-debounce", client=client)

    await asyncio.sleep(0.15)

    deliver.assert_awaited_once_with(
        "source-debounce",
        client=client,
        command_service=None,
        source_computer=None,
    )
    assert "source-debounce" not in conversation_delivery._pending_deliveries


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_debounced_delivery_separated_signals_fire_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two signals separated by more than the debounce window produce TWO
    independent deliveries."""
    monkeypatch.setattr("teleclaude.core.conversation_delivery._DEBOUNCE_WINDOW_S", 0.05)
    deliver = AsyncMock(return_value=1)
    monkeypatch.setattr("teleclaude.core.conversation_delivery.deliver_pending_conversation_updates", deliver)

    client = MagicMock()
    schedule_debounced_delivery("source-twin", client=client)
    await asyncio.sleep(0.10)
    schedule_debounced_delivery("source-twin", client=client)
    await asyncio.sleep(0.10)

    assert deliver.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_debounced_delivery_does_not_orphan_newer_task_when_old_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a fresh signal arrives while an earlier delivery is still running,
    the earlier task's completion must NOT clear the registry slot — that slot
    now points to the newer pending task and clearing it would orphan it,
    breaking coalescing for subsequent signals."""
    monkeypatch.setattr("teleclaude.core.conversation_delivery._DEBOUNCE_WINDOW_S", 0.02)

    deliver_start = asyncio.Event()
    deliver_release = asyncio.Event()

    async def slow_deliver(*args: object, **kwargs: object) -> int:
        deliver_start.set()
        await deliver_release.wait()
        return 1

    monkeypatch.setattr("teleclaude.core.conversation_delivery.deliver_pending_conversation_updates", slow_deliver)

    client = MagicMock()
    schedule_debounced_delivery("source-race", client=client)
    await asyncio.wait_for(deliver_start.wait(), timeout=1.0)

    schedule_debounced_delivery("source-race", client=client)
    new_task = conversation_delivery._pending_deliveries.get("source-race")
    assert new_task is not None
    deliver_release.set()
    await asyncio.sleep(0.005)
    assert conversation_delivery._pending_deliveries.get("source-race") is new_task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_replays_bounded_bundle_on_crash_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crash-recovery contract: when a previous attempt persisted
    ``pending_through_ts`` but didn't reach the cursor-advance step, replay
    must re-send the SAME bounded bundle (segments capped at the pending bound)
    under the SAME dedupe key."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    pending_iso = datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat()
    persisted = SimpleNamespace(
        delivered_through_ts=_LINK_FLOOR_ISO,
        pending_through_ts=pending_iso,
    )
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=persisted),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    bounded_segment = ConversationSegment(
        role="assistant",
        text="bundle that may or may not have reached the receiver",
        timestamp=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(return_value=[bounded_segment]),
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert command_service.process_message.await_count == 1
    sent_command = command_service.process_message.await_args_list[0].args[0]
    assert sent_command.text.startswith("[TeleClaude - Peer ")
    assert "bundle that may or may not have reached the receiver" in sent_command.text
    db.upsert_conversation_delivery_state.assert_awaited_once_with(
        link_id="link-001",
        source_session_id="source-001",
        target_session_id="target-001",
        delivered_through_ts=pending_iso,
        pending_through_ts=None,
    )
    assert delivered == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_does_not_advance_when_transcript_pruned_past_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the transcript no longer contains the bounded range, the cursor must
    NOT advance. Faking durable handoff under that condition is silent data
    loss; staying stuck is the correct behavior, surfaced via an error log."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    pending_iso = datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat()
    persisted = SimpleNamespace(
        delivered_through_ts=_LINK_FLOOR_ISO,
        pending_through_ts=pending_iso,
    )
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=persisted),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(return_value=[]),
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 0
    command_service.process_message.assert_not_awaited()
    db.upsert_conversation_delivery_state.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_does_not_advance_when_replay_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the replay send raises, the cursor must NOT advance and pending
    must remain in place, so the next reconciliation tries again."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock(side_effect=RuntimeError("network down")))
    client = MagicMock()
    pending_iso = datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat()
    persisted = SimpleNamespace(
        delivered_through_ts=_LINK_FLOOR_ISO,
        pending_through_ts=pending_iso,
    )
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=persisted),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(
            return_value=[
                ConversationSegment(
                    role="assistant",
                    text="payload",
                    timestamp=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC),
                )
            ]
        ),
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 0
    db.upsert_conversation_delivery_state.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_writes_pending_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-send pending write: the planned upper-bound must hit the DB BEFORE
    the bundled ``process_message`` call, so a crash between send and cursor
    advance is recoverable."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    write_log: list[str] = []

    async def record_send(*args: object, **kwargs: object) -> None:
        write_log.append("send")

    async def record_upsert(**kwargs: object) -> None:
        if kwargs.get("pending_through_ts") is None and kwargs.get("delivered_through_ts"):
            write_log.append("clear-pending+advance")
        elif kwargs.get("pending_through_ts"):
            write_log.append("pre-pending")

    command_service = SimpleNamespace(process_message=AsyncMock(side_effect=record_send))
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=_persisted_at_floor()),
        upsert_conversation_delivery_state=AsyncMock(side_effect=record_upsert),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(
            return_value=[
                ConversationSegment(
                    role="assistant",
                    text="some output",
                    timestamp=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC),
                )
            ]
        ),
    )

    await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert write_log == ["pre-pending", "send", "clear-pending+advance"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_drops_trailing_user_segment_so_human_turn_waits_for_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trailing ``user`` segment means the human typed but the agent has not
    yet replied. Shipping it now would deliver an unanswered human turn to the
    peer. The bundle must be trimmed to the last assistant turn; the held-back
    user segment stays past the cursor and rides with the next agent_stop's
    reply.
    """
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=_persisted_at_floor()),
        upsert_conversation_delivery_state=AsyncMock(),
    )
    user_replied_to = ConversationSegment(
        role="user",
        text="Earlier human turn that the agent already addressed.",
        timestamp=datetime(2026, 4, 14, 10, 1, 0, tzinfo=UTC),
    )
    assistant_reply = ConversationSegment(
        role="assistant",
        text="The reply attached to the earlier human turn.",
        timestamp=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC),
    )
    trailing_user = ConversationSegment(
        role="user",
        text="Brand-new human turn that the agent has not answered yet.",
        timestamp=datetime(2026, 4, 14, 10, 3, 0, tzinfo=UTC),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(return_value=[user_replied_to, assistant_reply, trailing_user]),
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 1
    assert command_service.process_message.await_count == 1
    sole_call = command_service.process_message.await_args_list[0].args[0]
    assert user_replied_to.text in sole_call.text
    assert assistant_reply.text in sole_call.text
    assert trailing_user.text not in sole_call.text
    assert db.upsert_conversation_delivery_state.await_count == 2
    pre_call = db.upsert_conversation_delivery_state.await_args_list[0].kwargs
    advance_call = db.upsert_conversation_delivery_state.await_args_list[1].kwargs
    assert pre_call["pending_through_ts"] == assistant_reply.timestamp.isoformat()
    assert advance_call["delivered_through_ts"] == assistant_reply.timestamp.isoformat()
    assert advance_call["pending_through_ts"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_backfills_missing_cursor_from_link_created_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If an active link has no `conversation_delivery_state` row, the delivery
    path must self-heal by writing a backfilled cursor anchored at the link's
    creation timestamp — NOT at "now" — so any post-link transcript content
    that hasn't been delivered yet is still recoverable. This is the
    caller-visible contract: a missing cursor never causes a permanent stuck
    state, and recoverable peer output is not silently dropped."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link_created_at = datetime(2026, 4, 14, 9, 0, 0, tzinfo=UTC)
    link = SimpleNamespace(link_id="link-orphan", created_at=link_created_at)
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=None),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    post_link_segment = ConversationSegment(
        role="assistant",
        text="Reply that arrived after the link was established but before repair.",
        timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
    )
    collect = AsyncMock(return_value=[post_link_segment])
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        collect,
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    # The post-link segment IS delivered — repair recovered it from the link
    # floor instead of anchoring at "now" and dropping it.
    assert delivered == 1
    command_service.process_message.assert_awaited_once()
    sent_command = command_service.process_message.await_args.args[0]
    assert post_link_segment.text in sent_command.text

    # First upsert: backfill at link.created_at.
    backfill_kwargs = db.upsert_conversation_delivery_state.await_args_list[0].kwargs
    assert backfill_kwargs["link_id"] == "link-orphan"
    assert backfill_kwargs["source_session_id"] == "source-001"
    assert backfill_kwargs["target_session_id"] == "target-001"
    assert backfill_kwargs["delivered_through_ts"] == link_created_at.isoformat()
    assert backfill_kwargs["pending_through_ts"] is None

    # Collector was called with the link.created_at floor — that's the
    # invariant: missing cursor recovers from the link's real creation point,
    # not from "now".
    collect.assert_awaited_once()
    assert collect.await_args.args[2] == link_created_at


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_strips_all_machine_originated_user_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public-boundary regression: when the source transcript contains user
    blocks that are actually machine-injected pastes (peer bridges, orchestrator
    / integrator / system dispatches), the bundled message delivered to the
    peer must NOT contain any of them. Re-shipping machine framing as Human
    segments creates a ping-pong loop where each side echoes the other's last
    bundle back. All four canonical machine-role headers are exercised.
    """

    # Claude transcript entries: user content can be a plain string; assistant
    # content is a list of typed blocks. Match that shape so the projector
    # accepts both roles without falling through its non-list-content guard.
    def _entry(role: str, text: str, ts: str) -> dict[str, object]:  # guard: loose-dict
        if role == "user":
            return {"timestamp": ts, "message": {"role": role, "content": text}}
        return {
            "timestamp": ts,
            "message": {"role": role, "content": [{"type": "text", "text": text}]},
        }

    # All entry timestamps are strictly AFTER the per-link cursor floor so the
    # projector's `<= since` filter doesn't eat the real human turn.
    # Mix: real human input, one block per machine-role header, agent reply.
    entries = [
        _entry("user", "What is the status?", "2026-04-14T10:00:01.000Z"),
        _entry(
            "user",
            "[TeleClaude - Peer (peer-id) on host]\n\n--- Agent @ ts ---\nx",
            "2026-04-14T10:01:00.000Z",
        ),
        _entry(
            "user",
            "[Orchestrator (orch-id) on host]\n\nDispatch reason",
            "2026-04-14T10:02:00.000Z",
        ),
        _entry(
            "user",
            "[Integrator (int-id) on host]\n\nMerge complete",
            "2026-04-14T10:03:00.000Z",
        ),
        _entry(
            "user",
            "[System (sys-id) on host]\n\nMaintenance notice",
            "2026-04-14T10:04:00.000Z",
        ),
        _entry("assistant", "Status: nominal.", "2026-04-14T10:05:00.000Z"),
    ]

    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=_persisted_at_floor()),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    # Mock only the on-disk read; the rest of the path runs end-to-end:
    # project_entries, the machine-originated filter, the bundler, the dispatcher.
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._get_entries_for_agent",
        lambda *args, **kwargs: entries,
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 1
    assert command_service.process_message.await_count == 1
    body = command_service.process_message.await_args_list[0].args[0].text
    # The real human turn and the assistant reply make it through.
    assert "What is the status?" in body
    assert "Status: nominal." in body
    # None of the machine-role headers leak into the bundle as Human segments.
    assert "[TeleClaude - Peer (peer-id)" not in body
    assert "[Orchestrator (orch-id)" not in body
    assert "[Integrator (int-id)" not in body
    assert "[System (sys-id)" not in body
    # Sanity: only one Human marker (the real turn) — not five.
    assert body.count("--- Human @") == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deliver_pending_conversation_updates_skips_delivery_when_only_a_trailing_user_segment_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare unanswered human turn with no assistant turn since the cursor
    yields no deliverable bundle. The peer must not receive the human's words
    until the agent replies; the cursor must stay where it is.
    """
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    db = SimpleNamespace(
        get_session=AsyncMock(return_value=source),
        get_conversation_delivery_state=AsyncMock(return_value=_persisted_at_floor()),
        upsert_conversation_delivery_state=AsyncMock(),
    )

    monkeypatch.setattr("teleclaude.core.conversation_delivery.db", db)
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_active_links_for_session",
        AsyncMock(return_value=[link]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery.get_peer_members",
        AsyncMock(return_value=[peer]),
    )
    monkeypatch.setattr(
        "teleclaude.core.conversation_delivery._collect_visible_conversation_segments_since",
        AsyncMock(
            return_value=[
                ConversationSegment(
                    role="user",
                    text="Unanswered human turn — nothing to bundle yet.",
                    timestamp=datetime(2026, 4, 14, 10, 1, 0, tzinfo=UTC),
                )
            ]
        ),
    )

    delivered = await deliver_pending_conversation_updates(
        "source-001",
        client=client,
        command_service=command_service,
    )

    assert delivered == 0
    assert command_service.process_message.await_count == 0
    assert db.upsert_conversation_delivery_state.await_count == 0
