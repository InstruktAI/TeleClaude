"""Unit tests for WhatsApp delivery helpers."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.services.whatsapp import send_whatsapp_message

_BASE_URL = "https://graph.facebook.com/v21.0/phone-id-1/messages"


def _ok_response(message_id: str = "wamid.HBgLMTIz") -> httpx.Response:
    return httpx.Response(
        200,
        json={"messaging_product": "whatsapp", "messages": [{"id": message_id}]},
        request=httpx.Request("POST", _BASE_URL),
    )


def _error_response(message: str = "Invalid parameter", status: int = 400) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "OAuthException", "code": 100}},
        request=httpx.Request("POST", _BASE_URL),
    )


def _mock_client(response: httpx.Response) -> MagicMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_send_message_success() -> None:
    mock = _mock_client(_ok_response("wamid.abc123"))

    with patch("teleclaude.services.whatsapp.httpx.AsyncClient", return_value=mock):
        result = await send_whatsapp_message(
            phone_number="+1234567890",
            content="hello world",
            phone_number_id="phone-id-1",
            access_token="token-abc",
        )

    assert result == "wamid.abc123"
    mock.__aenter__.return_value.post.assert_awaited_once()
    call_kwargs = mock.__aenter__.return_value.post.call_args.kwargs
    assert call_kwargs["json"]["messaging_product"] == "whatsapp"
    assert call_kwargs["json"]["to"] == "+1234567890"
    assert call_kwargs["json"]["type"] == "text"


@pytest.mark.asyncio
async def test_missing_access_token_raises() -> None:
    with pytest.raises(ValueError, match="access_token"):
        await send_whatsapp_message(
            phone_number="+1234567890",
            content="hello",
            phone_number_id="phone-id-1",
            access_token="",
        )


@pytest.mark.asyncio
async def test_empty_content_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        await send_whatsapp_message(
            phone_number="+1234567890",
            content="",
            phone_number_id="phone-id-1",
            access_token="token-abc",
        )


@pytest.mark.asyncio
async def test_api_error_raises() -> None:
    mock = _mock_client(_error_response("Invalid parameter", 400))

    with patch("teleclaude.services.whatsapp.httpx.AsyncClient", return_value=mock):
        with pytest.raises(RuntimeError, match="HTTP 400"):
            await send_whatsapp_message(
                phone_number="+1234567890",
                content="hello",
                phone_number_id="phone-id-1",
                access_token="token-abc",
            )


@pytest.mark.asyncio
async def test_truncation_warning() -> None:
    long_content = "x" * 5000
    mock = _mock_client(_ok_response("wamid.long"))

    with patch("teleclaude.services.whatsapp.httpx.AsyncClient", return_value=mock):
        with patch("teleclaude.services.whatsapp.logger") as mock_logger:
            result = await send_whatsapp_message(
                phone_number="+1234567890",
                content=long_content,
                phone_number_id="phone-id-1",
                access_token="token-abc",
            )

    assert result == "wamid.long"
    mock_logger.warning.assert_called_once()
    call_args = mock_logger.warning.call_args
    assert "truncated" in call_args[0][0]
