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
    format_bundled_conversation_message,
    is_conversation_bridge_message,
)
from teleclaude.core.models import Session


def _session(**kwargs: object) -> Session:
    defaults = {
        "session_id": "source-001",
        "computer_name": "local",
        "tmux_session_name": "tc-source-001",
        "title": "Source Session",
        "active_agent": "claude",
        "native_log_file": "/tmp/source.jsonl",
        "last_conversation_injected_at": datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return Session(**defaults)


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
        get_conversation_delivery_state=AsyncMock(return_value=None),
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
    # Outer wrapper marks the entire bundle as system-injected
    assert sole_call.text.startswith("[TeleClaude Conversation update from ")
    # Inner markers preserve temporal sequence — user turn before assistant turn
    user_marker_idx = sole_call.text.find("--- Human in the Loop @")
    assistant_marker_idx = sole_call.text.find("--- Linked output @")
    assert user_marker_idx != -1
    assert assistant_marker_idx != -1
    assert user_marker_idx < assistant_marker_idx
    # Both segment bodies must be present
    assert "Please inspect the changed API contract." in sole_call.text
    assert "I narrowed the regression to the linked replay path." in sole_call.text
    # Two upserts per delivery: pre-pending (planned upper bound, before send),
    # then clear-pending+advance (delivered timestamp, after send). The cursor
    # advances ONCE per bundle (not per segment); pre-pending is the crash-
    # recovery safety net.
    assert db.upsert_conversation_delivery_state.await_count == 2
    pre_call = db.upsert_conversation_delivery_state.await_args_list[0].kwargs
    advance_call = db.upsert_conversation_delivery_state.await_args_list[1].kwargs
    assert pre_call == {
        "link_id": "link-001",
        "source_session_id": "source-001",
        "target_session_id": "target-001",
        "delivered_through_ts": None,
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
    # The pre-pending write happens before the send (it's the crash-recovery
    # safety net) so ONE upsert is expected even on failure. The "advance"
    # upsert (with delivered_through_ts set) must NOT happen — that's the
    # invariant: cursor stays at its previous position when send fails.
    assert db.upsert_conversation_delivery_state.await_count == 1
    pre_call = db.upsert_conversation_delivery_state.await_args_list[0].kwargs
    assert pre_call["delivered_through_ts"] is None
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
def test_format_bundled_conversation_message_orders_markers_chronologically() -> None:
    """Bundled body wraps the whole delta in one outer header and emits one
    inner marker per segment in temporal order, with role-specific labels."""
    body = format_bundled_conversation_message(
        sender_label="A",
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[
            ("user", datetime(2026, 5, 4, 9, 50, 10, tzinfo=UTC), "tail your pair"),
            ("assistant", datetime(2026, 5, 4, 9, 51, 42, tzinfo=UTC), "checking now"),
            ("assistant", datetime(2026, 5, 4, 9, 52, 18, tzinfo=UTC), "found the issue"),
        ],
    )
    assert body.startswith('[TeleClaude Conversation update from "A" (sess-a) on MozBook]')
    user_idx = body.find("--- Human in the Loop @ 2026-05-04T09:50:10")
    first_assistant_idx = body.find("--- Linked output @ 2026-05-04T09:51:42")
    second_assistant_idx = body.find("--- Linked output @ 2026-05-04T09:52:18")
    assert -1 < user_idx < first_assistant_idx < second_assistant_idx
    assert "tail your pair" in body
    assert "checking now" in body
    assert "found the issue" in body


@pytest.mark.unit
def test_format_bundled_conversation_message_handles_missing_timestamp() -> None:
    body = format_bundled_conversation_message(
        sender_label="A",
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[("assistant", None, "no timestamp")],
    )
    assert "--- Linked output @ unknown ---" in body
    assert "no timestamp" in body


@pytest.mark.unit
def test_format_bundled_conversation_message_empty_segments_returns_empty_string() -> None:
    body = format_bundled_conversation_message(
        sender_label="A",
        sender_session_id="sess-a",
        sender_computer="MozBook",
        segments=[],
    )
    assert body == ""


@pytest.mark.unit
def test_is_conversation_bridge_message_recognizes_bundled_prefix() -> None:
    """The new bundled prefix must be recognized as a bridge message so the
    inbound message handler does NOT skip tmux injection (which would prevent
    the receiver from ever seeing the bundle)."""
    body = format_bundled_conversation_message(
        sender_label="A",
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

    # Wait past the debounce window (after the LAST signal) for the firing.
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
    await asyncio.sleep(0.10)  # first window expires + delivery completes
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
    # Wait for the first delivery to enter its body (past the debounce sleep).
    await asyncio.wait_for(deliver_start.wait(), timeout=1.0)

    # Now schedule a fresh signal — this must register a NEW pending task
    # (the old task is mid-delivery and will be cancelled/orphaned shortly).
    schedule_debounced_delivery("source-race", client=client)
    new_task = conversation_delivery._pending_deliveries.get("source-race")
    assert new_task is not None
    # Releasing the slow delivery lets the OLD task's finally block run. The
    # registry slot now belongs to the NEW task — the old task's finally must
    # NOT pop it.
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
    under the SAME dedupe key. The receiver dedupes if it already got the
    bundle, or processes it for the first time if the prior send did NOT reach
    the queue. Cursor advances only after this replay handoff succeeds —
    blindly promoting pending to delivered would lose content if the prior
    send actually failed."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock())
    client = MagicMock()
    pending_iso = datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat()
    persisted = SimpleNamespace(
        delivered_through_ts=None,
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

    # Replay re-sent the bounded bundle exactly once.
    assert command_service.process_message.await_count == 1
    sent_command = command_service.process_message.await_args_list[0].args[0]
    assert sent_command.text.startswith("[TeleClaude Conversation update from ")
    assert "bundle that may or may not have reached the receiver" in sent_command.text
    # After successful replay, cursor advances to pending bound and pending is
    # cleared — atomically, in a single upsert.
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
async def test_deliver_pending_conversation_updates_does_not_advance_when_replay_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the replay send raises, the cursor must NOT advance and pending
    must remain in place, so the next reconciliation tries again. Without this
    invariant, undelivered content could be marked delivered and lost."""
    source = _session()
    peer = SimpleNamespace(session_id="target-001", computer_name="local")
    link = SimpleNamespace(link_id="link-001")
    command_service = SimpleNamespace(process_message=AsyncMock(side_effect=RuntimeError("network down")))
    client = MagicMock()
    pending_iso = datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat()
    persisted = SimpleNamespace(
        delivered_through_ts=None,
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
    # Critical: NO upsert — pending stays at its previous value, cursor does
    # not advance, the next reconciliation will retry.
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
        get_conversation_delivery_state=AsyncMock(return_value=None),
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

    # Strict ordering: pre-pending write, THEN send, THEN clear-pending+advance.
    assert write_log == ["pre-pending", "send", "clear-pending+advance"]
