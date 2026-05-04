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
    # Cursor advances ONCE to the latest segment timestamp, not twice
    db.upsert_conversation_delivery_state.assert_awaited_once_with(
        link_id="link-001",
        source_session_id="source-001",
        target_session_id="target-001",
        delivered_through_ts=datetime(2026, 4, 14, 10, 2, 0, tzinfo=UTC).isoformat(),
    )


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
    db.upsert_conversation_delivery_state.assert_not_awaited()


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
