"""Unit tests for Discord delivery helpers."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.services.discord import send_discord_dm


def _ok_dm_response(channel_id: str = "chan-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={"id": channel_id, "type": 1},
        request=httpx.Request("POST", "https://discord.com/api/v10/users/@me/channels"),
    )


def _ok_msg_response(message_id: str = "msg-42") -> httpx.Response:
    return httpx.Response(
        200,
        json={"id": message_id, "content": "hello"},
        request=httpx.Request("POST", "https://discord.com/api/v10/channels/chan-1/messages"),
    )


def _error_response(message: str = "Unknown User", status: int = 400, url: str = "https://discord.com/api/v10") -> httpx.Response:
    return httpx.Response(
        status,
        json={"message": message, "code": 10013},
        request=httpx.Request("POST", url),
    )


def _mock_client_two_responses(first: httpx.Response, second: httpx.Response) -> MagicMock:
    """Create a mock async context manager that returns a client whose post() returns responses in order."""
    client = AsyncMock()
    client.post = AsyncMock(side_effect=[first, second])
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_client_one_response(response: httpx.Response) -> MagicMock:
    """Create a mock async context manager returning one response."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_send_dm_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    mock = _mock_client_two_responses(_ok_dm_response("chan-99"), _ok_msg_response("msg-77"))

    with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=mock):
        result = await send_discord_dm(user_id="user-123", content="hello world")

    assert result == "msg-77"
    assert mock.__aenter__.return_value.post.call_count == 2


@pytest.mark.asyncio
async def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Missing Discord bot token"):
        await send_discord_dm(user_id="user-123", content="hello")


@pytest.mark.asyncio
async def test_empty_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    with pytest.raises(ValueError, match="empty"):
        await send_discord_dm(user_id="user-123", content="")


@pytest.mark.asyncio
async def test_api_error_on_dm_channel_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    error = _error_response("Unknown User", 400, "https://discord.com/api/v10/users/@me/channels")
    mock = _mock_client_one_response(error)

    with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=mock):
        with pytest.raises(RuntimeError, match="HTTP 400"):
            await send_discord_dm(user_id="bad-user", content="hello")


@pytest.mark.asyncio
async def test_api_error_on_send_message_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    error_msg = _error_response("Missing Permissions", 403, "https://discord.com/api/v10/channels/chan-1/messages")
    mock = _mock_client_two_responses(_ok_dm_response("chan-1"), error_msg)

    with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=mock):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            await send_discord_dm(user_id="user-123", content="hello")


@pytest.mark.asyncio
async def test_truncation_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    long_content = "x" * 2500
    mock = _mock_client_two_responses(_ok_dm_response("chan-1"), _ok_msg_response("msg-1"))

    with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=mock):
        with patch("teleclaude.services.discord.logger") as mock_logger:
            result = await send_discord_dm(user_id="user-123", content=long_content)

    assert result == "msg-1"
    mock_logger.warning.assert_called_once()
    call_args = mock_logger.warning.call_args
    assert "truncated" in call_args[0][0]
