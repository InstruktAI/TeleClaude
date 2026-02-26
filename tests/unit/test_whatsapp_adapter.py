"""Unit tests for WhatsApp adapter behavior and metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.whatsapp_adapter import WhatsAppAdapter
from teleclaude.core.models import Session, SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, object],  # guard: loose-dict - Mock JSON.
        status_code: int = 200,
        headers: dict[str, str] | None = None,  # guard: loose-dict - Mock HTTP headers.
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:  # guard: loose-dict - Mock JSON.
        return self._payload


@pytest.fixture
def customer_session() -> Session:
    meta = SessionAdapterMetadata()
    whatsapp = meta.get_ui().get_whatsapp()
    whatsapp.phone_number = "15551234567"

    return Session(
        session_id="session-whatsapp",
        computer_name="test-computer",
        tmux_session_name="tc_whatsapp",
        title="WhatsApp Customer",
        last_input_origin=InputOrigin.WHATSAPP.value,
        adapter_metadata=meta,
        human_role="customer",
    )


@pytest.fixture
def adapter() -> WhatsAppAdapter:
    wa = WhatsAppAdapter(SimpleNamespace())
    wa._access_token = "test-token"
    wa._phone_number_id = "123456"
    return wa


@pytest.mark.asyncio
async def test_send_message_posts_text_payload(adapter: WhatsAppAdapter, customer_session: Session) -> None:
    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(return_value=_FakeResponse({"messages": [{"id": "wamid.123"}]}))

    message_id = await adapter.send_message(customer_session, "hello from bot")

    assert message_id == "wamid.123"
    adapter._http.post.assert_awaited_once()
    call = adapter._http.post.await_args
    assert call.args[0].endswith("/messages")
    assert call.kwargs["json"]["type"] == "text"
    assert call.kwargs["json"]["text"]["body"] == "hello from bot"


@pytest.mark.asyncio
async def test_send_message_retries_on_429(adapter: WhatsAppAdapter, customer_session: Session) -> None:
    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(
        side_effect=[
            _FakeResponse({}, status_code=429, headers={"Retry-After": "0.01"}),
            _FakeResponse({"messages": [{"id": "wamid.retry"}]}),
        ]
    )

    with patch("teleclaude.adapters.whatsapp_adapter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        message_id = await adapter.send_message(customer_session, "hello after backoff")

    assert message_id == "wamid.retry"
    assert adapter._http.post.await_count == 2
    sleep_mock.assert_awaited_once_with(0.01)


@pytest.mark.asyncio
async def test_send_message_raises_after_exhausting_429_retries(
    adapter: WhatsAppAdapter, customer_session: Session
) -> None:
    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(side_effect=[_FakeResponse({}, status_code=429) for _ in range(4)])

    with patch("teleclaude.adapters.whatsapp_adapter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            await adapter.send_message(customer_session, "still throttled")

    assert adapter._http.post.await_count == 4
    assert sleep_mock.await_count == 3


@pytest.mark.asyncio
async def test_send_message_splits_long_text(adapter: WhatsAppAdapter, customer_session: Session) -> None:
    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(
        side_effect=[
            _FakeResponse({"messages": [{"id": "wamid.1"}]}),
            _FakeResponse({"messages": [{"id": "wamid.2"}]}),
        ]
    )

    long_text = "x" * 5000
    message_id = await adapter.send_message(customer_session, long_text)

    assert message_id == "wamid.2"
    assert adapter._http.post.await_count == 2


@pytest.mark.asyncio
async def test_send_message_uses_template_outside_24h_window(
    adapter: WhatsAppAdapter, customer_session: Session
) -> None:
    adapter._template_name = "support_outside_window"
    adapter._template_language = "en_US"

    whatsapp = customer_session.get_metadata().get_ui().get_whatsapp()
    whatsapp.last_customer_message_at = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()

    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(return_value=_FakeResponse({"messages": [{"id": "wamid.tpl"}]}))

    message_id = await adapter.send_message(customer_session, "Outside window")

    assert message_id == "wamid.tpl"
    payload = adapter._http.post.await_args.kwargs["json"]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "support_outside_window"


@pytest.mark.asyncio
async def test_send_typing_indicator_uses_read_receipt(adapter: WhatsAppAdapter, customer_session: Session) -> None:
    whatsapp = customer_session.get_metadata().get_ui().get_whatsapp()
    whatsapp.last_received_message_id = "wamid.inbound.1"

    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(return_value=_FakeResponse({"success": True}))

    await adapter.send_typing_indicator(customer_session)

    payload = adapter._http.post.await_args.kwargs["json"]
    assert payload["status"] == "read"
    assert payload["message_id"] == "wamid.inbound.1"


@pytest.mark.asyncio
async def test_send_file_uploads_media_then_sends_message(
    adapter: WhatsAppAdapter, customer_session: Session, tmp_path: Path
) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("hello", encoding="utf-8")

    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(
        side_effect=[
            _FakeResponse({"id": "media.1"}),
            _FakeResponse({"messages": [{"id": "wamid.file.1"}]}),
        ]
    )

    message_id = await adapter.send_file(customer_session, str(f), caption="file caption")

    assert message_id == "wamid.file.1"
    assert adapter._http.post.await_count == 2


@pytest.mark.asyncio
async def test_send_file_retries_media_upload_on_429(
    adapter: WhatsAppAdapter, customer_session: Session, tmp_path: Path
) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("hello", encoding="utf-8")

    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(
        side_effect=[
            _FakeResponse({}, status_code=429, headers={"Retry-After": "0.01"}),
            _FakeResponse({"id": "media.retry"}),
            _FakeResponse({"messages": [{"id": "wamid.file.retry"}]}),
        ]
    )

    with patch("teleclaude.adapters.whatsapp_adapter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        message_id = await adapter.send_file(customer_session, str(f), caption="file caption")

    assert message_id == "wamid.file.retry"
    assert adapter._http.post.await_count == 3
    sleep_mock.assert_awaited_once_with(0.01)


@pytest.mark.asyncio
async def test_send_file_raises_after_exhausting_media_upload_429_retries(
    adapter: WhatsAppAdapter, customer_session: Session, tmp_path: Path
) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("hello", encoding="utf-8")

    adapter._http = AsyncMock()
    adapter._http.post = AsyncMock(side_effect=[_FakeResponse({}, status_code=429) for _ in range(4)])

    with patch("teleclaude.adapters.whatsapp_adapter.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            await adapter.send_file(customer_session, str(f), caption="file caption")

    assert adapter._http.post.await_count == 4
    assert sleep_mock.await_count == 3


def test_markdown_conversion_for_whatsapp(adapter: WhatsAppAdapter) -> None:
    converted = adapter._convert_markdown_for_platform("**bold** ~~gone~~ `code`")

    assert "*bold*" in converted
    assert "~gone~" in converted
    assert "```code```" in converted


def test_whatsapp_metadata_roundtrip() -> None:
    metadata = SessionAdapterMetadata()
    whatsapp = metadata.get_ui().get_whatsapp()
    whatsapp.phone_number = "15551234567"
    whatsapp.output_message_id = "wamid.out.1"
    whatsapp.last_customer_message_at = "2026-02-26T00:00:00+00:00"

    serialized = metadata.to_json()
    restored = SessionAdapterMetadata.from_json(serialized)

    restored_whatsapp = restored.get_ui().get_whatsapp()
    assert restored_whatsapp.phone_number == "15551234567"
    assert restored_whatsapp.output_message_id == "wamid.out.1"
    assert restored_whatsapp.last_customer_message_at == "2026-02-26T00:00:00+00:00"
