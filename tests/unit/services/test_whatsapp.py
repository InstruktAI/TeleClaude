"""Characterization tests for teleclaude.services.whatsapp."""

from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import patch

import pytest

from teleclaude.services.whatsapp import WHATSAPP_MAX_MESSAGE_LENGTH, send_whatsapp_message


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _RecordingAsyncClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[Mapping[str, object]] = []

    async def __aenter__(self) -> _RecordingAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)


class TestSendWhatsappMessage:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("phone_number", "content", "phone_number_id", "access_token", "message"),
        [
            ("", "hello", "pnid", "token", "phone_number is required"),
            ("+15555550123", "   ", "pnid", "token", "Notification content is empty"),
            ("+15555550123", "hello", "", "token", "phone_number_id is required"),
            ("+15555550123", "hello", "pnid", "", "access_token is required"),
        ],
    )
    async def test_validates_required_inputs(
        self,
        phone_number: str,
        content: str,
        phone_number_id: str,
        access_token: str,
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            await send_whatsapp_message(
                phone_number,
                content,
                phone_number_id=phone_number_id,
                access_token=access_token,
            )

    @pytest.mark.unit
    async def test_sends_message_and_returns_id(self) -> None:
        client = _RecordingAsyncClient([_FakeResponse(200, {"messages": [{"id": "wamid-7"}]})])

        with patch("teleclaude.services.whatsapp.httpx.AsyncClient", return_value=client):
            message_id = await send_whatsapp_message(
                "+15555550123",
                "x" * (WHATSAPP_MAX_MESSAGE_LENGTH + 11),
                phone_number_id="phone-number-id",
                access_token="token-123",
            )

        assert message_id == "wamid-7"
        assert client.calls[0]["json"] == {
            "messaging_product": "whatsapp",
            "to": "+15555550123",
            "type": "text",
            "text": {"body": "x" * WHATSAPP_MAX_MESSAGE_LENGTH},
        }

    @pytest.mark.unit
    async def test_raises_with_api_error_detail(self) -> None:
        client = _RecordingAsyncClient(
            [_FakeResponse(500, {"error": {"message": "Upstream unavailable"}}, text="downstream error")]
        )

        with patch("teleclaude.services.whatsapp.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="WhatsApp send failed \\(HTTP 500\\): Upstream unavailable"):
                await send_whatsapp_message(
                    "+15555550123",
                    "hello",
                    phone_number_id="phone-number-id",
                    access_token="token-123",
                )
