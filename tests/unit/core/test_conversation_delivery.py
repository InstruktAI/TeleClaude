from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.conversation_delivery import (
    ConversationSegment,
    deliver_pending_conversation_updates,
    reconcile_outstanding_conversation_deliveries,
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
async def test_deliver_pending_conversation_updates_delivers_mixed_segments_and_advances_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    assert delivered == 2
    assert command_service.process_message.await_count == 2
    first_call = command_service.process_message.await_args_list[0].args[0]
    second_call = command_service.process_message.await_args_list[1].args[0]
    assert first_call.source_message_id is not None
    assert second_call.source_message_id is not None
    assert first_call.text.startswith("[TeleClaude Human in the Loop")
    assert second_call.text.startswith("[TeleClaude Linked output from ")
    db.upsert_conversation_delivery_state.assert_awaited_with(
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
