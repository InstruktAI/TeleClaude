"""Tests for WhatsAppDeliveryAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude_events.delivery.whatsapp import WhatsAppDeliveryAdapter
from teleclaude_events.envelope import EventLevel


@pytest.fixture
def send_fn() -> AsyncMock:
    return AsyncMock(return_value="wamid.abc123")


@pytest.fixture
def adapter(send_fn: AsyncMock) -> WhatsAppDeliveryAdapter:
    return WhatsAppDeliveryAdapter(
        phone_number="+1234567890",
        send_fn=send_fn,
        min_level=int(EventLevel.WORKFLOW),
    )


@pytest.mark.asyncio
async def test_sends_when_created_and_level_meets_threshold(
    adapter: WhatsAppDeliveryAdapter, send_fn: AsyncMock
) -> None:
    await adapter.on_notification(
        notification_id=1,
        event_type="test.event",
        level=int(EventLevel.WORKFLOW),
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()
    call_kwargs = send_fn.call_args.kwargs
    assert call_kwargs["phone_number"] == "+1234567890"
    assert "test.event" in call_kwargs["content"]
    assert "1" in call_kwargs["content"]


@pytest.mark.asyncio
async def test_skips_when_not_created(adapter: WhatsAppDeliveryAdapter, send_fn: AsyncMock) -> None:
    await adapter.on_notification(
        notification_id=2,
        event_type="test.event",
        level=int(EventLevel.WORKFLOW),
        was_created=False,
        is_meaningful=True,
    )
    send_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_when_level_below_min(adapter: WhatsAppDeliveryAdapter, send_fn: AsyncMock) -> None:
    await adapter.on_notification(
        notification_id=3,
        event_type="system.daemon.restarted",
        level=int(EventLevel.INFRASTRUCTURE),  # below WORKFLOW threshold
        was_created=True,
        is_meaningful=False,
    )
    send_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_sends_when_level_above_min(adapter: WhatsAppDeliveryAdapter, send_fn: AsyncMock) -> None:
    await adapter.on_notification(
        notification_id=4,
        event_type="business.event",
        level=int(EventLevel.BUSINESS),  # above WORKFLOW threshold
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_handles_send_exception_gracefully(
    send_fn: AsyncMock,
) -> None:
    send_fn.side_effect = Exception("WhatsApp unreachable")
    adapter = WhatsAppDeliveryAdapter(
        phone_number="+9876543210",
        send_fn=send_fn,
        min_level=int(EventLevel.WORKFLOW),
    )
    # Should not raise
    await adapter.on_notification(
        notification_id=5,
        event_type="test.event",
        level=int(EventLevel.WORKFLOW),
        was_created=True,
        is_meaningful=True,
    )
    send_fn.assert_awaited_once()
