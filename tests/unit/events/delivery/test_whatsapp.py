"""Characterization tests for teleclaude.events.delivery.whatsapp."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude.events.delivery.whatsapp import WhatsAppDeliveryAdapter
from teleclaude.events.envelope import EventLevel


def _make_adapter(send_fn: AsyncMock, min_level: int = int(EventLevel.WORKFLOW)) -> WhatsAppDeliveryAdapter:
    return WhatsAppDeliveryAdapter(phone_number="+1234567890", send_fn=send_fn, min_level=min_level)


async def test_on_notification_sends_when_created_and_above_min_level() -> None:
    send_fn = AsyncMock(return_value="msg-id")
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=1,
        event_type="deployment.failed",
        level=int(EventLevel.BUSINESS),
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()
    call_kwargs = send_fn.call_args.kwargs
    assert call_kwargs["phone_number"] == "+1234567890"


async def test_on_notification_skips_when_not_created() -> None:
    send_fn = AsyncMock()
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=2,
        event_type="deployment.failed",
        level=int(EventLevel.BUSINESS),
        was_created=False,
        is_meaningful=True,
    )
    send_fn.assert_not_awaited()


async def test_on_notification_skips_when_level_below_min() -> None:
    send_fn = AsyncMock()
    adapter = _make_adapter(send_fn, min_level=int(EventLevel.WORKFLOW))
    await adapter.on_notification(
        notification_id=3,
        event_type="system.daemon.restarted",
        level=int(EventLevel.INFRASTRUCTURE),
        was_created=True,
        is_meaningful=False,
    )
    send_fn.assert_not_awaited()


async def test_on_notification_swallows_send_exceptions() -> None:
    send_fn = AsyncMock(side_effect=Exception("whatsapp api error"))
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=4,
        event_type="deployment.failed",
        level=int(EventLevel.BUSINESS),
        was_created=True,
        is_meaningful=True,
    )


async def test_default_min_level_is_workflow() -> None:
    send_fn = AsyncMock(return_value="x")
    adapter = WhatsAppDeliveryAdapter(phone_number="+0", send_fn=send_fn)
    await adapter.on_notification(
        notification_id=5,
        event_type="event",
        level=int(EventLevel.OPERATIONAL),
        was_created=True,
        is_meaningful=False,
    )
    send_fn.assert_not_awaited()


@pytest.mark.parametrize("level", [int(EventLevel.WORKFLOW), int(EventLevel.BUSINESS)])
async def test_sends_for_workflow_and_business_levels(level: int) -> None:
    send_fn = AsyncMock(return_value="ok")
    adapter = _make_adapter(send_fn)
    await adapter.on_notification(
        notification_id=6,
        event_type="test.event",
        level=level,
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()
