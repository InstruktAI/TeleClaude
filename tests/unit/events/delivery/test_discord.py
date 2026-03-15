"""Characterization tests for teleclaude.events.delivery.discord."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude.events.delivery.discord import DiscordDeliveryAdapter
from teleclaude.events.envelope import EventLevel


def _make_adapter(send_fn: AsyncMock, min_level: int = int(EventLevel.WORKFLOW)) -> DiscordDeliveryAdapter:
    return DiscordDeliveryAdapter(user_id="user-123", send_fn=send_fn, min_level=min_level)


async def test_on_notification_sends_when_created_and_above_min_level() -> None:
    send_fn = AsyncMock(return_value="msg-id")
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=1,
        event_type="deployment.started",
        level=int(EventLevel.WORKFLOW),
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()
    call_kwargs = send_fn.call_args.kwargs
    assert call_kwargs["user_id"] == "user-123"


async def test_on_notification_skips_when_not_created() -> None:
    send_fn = AsyncMock()
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=2,
        event_type="deployment.started",
        level=int(EventLevel.WORKFLOW),
        was_created=False,
        is_meaningful=True,
    )
    send_fn.assert_not_awaited()


async def test_on_notification_skips_when_level_below_min() -> None:
    send_fn = AsyncMock()
    adapter = _make_adapter(send_fn, min_level=int(EventLevel.WORKFLOW))
    await adapter.on_notification(
        notification_id=3,
        event_type="node.alive",
        level=int(EventLevel.INFRASTRUCTURE),
        was_created=True,
        is_meaningful=False,
    )
    send_fn.assert_not_awaited()


async def test_on_notification_swallows_send_exceptions() -> None:
    send_fn = AsyncMock(side_effect=RuntimeError("network error"))
    adapter = _make_adapter(send_fn)
    # Must not raise
    await adapter.on_notification(
        notification_id=4,
        event_type="deployment.started",
        level=int(EventLevel.WORKFLOW),
        was_created=True,
        is_meaningful=True,
    )


async def test_default_min_level_is_workflow() -> None:
    send_fn = AsyncMock(return_value="x")
    adapter = DiscordDeliveryAdapter(user_id="u", send_fn=send_fn)
    # OPERATIONAL (1) < WORKFLOW (2) → should not send
    await adapter.on_notification(
        notification_id=5,
        event_type="some.event",
        level=int(EventLevel.OPERATIONAL),
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_not_awaited()
    # BUSINESS (3) >= WORKFLOW (2) → should send
    await adapter.on_notification(
        notification_id=6,
        event_type="some.event",
        level=int(EventLevel.BUSINESS),
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()


@pytest.mark.parametrize("level", [int(EventLevel.WORKFLOW), int(EventLevel.BUSINESS)])
async def test_on_notification_sends_for_workflow_and_business_levels(level: int) -> None:
    send_fn = AsyncMock(return_value="ok")
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=7,
        event_type="test.event",
        level=level,
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()
