"""Characterization tests for teleclaude.services.discord."""

from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import patch

import pytest

from teleclaude.services.discord import DISCORD_MAX_MESSAGE_LENGTH, send_discord_dm


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


class TestSendDiscordDm:
    @pytest.mark.unit
    async def test_requires_bot_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="Missing Discord bot token"):
            await send_discord_dm("user-1", "hello")

    @pytest.mark.unit
    async def test_rejects_empty_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-123")
        with pytest.raises(ValueError, match="Notification content is empty"):
            await send_discord_dm("user-1", "   ")

    @pytest.mark.unit
    async def test_truncates_and_returns_message_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-123")
        client = _RecordingAsyncClient(
            [
                _FakeResponse(200, {"id": "channel-9"}),
                _FakeResponse(200, {"id": "message-7"}),
            ]
        )

        with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=client):
            message_id = await send_discord_dm("user-1", "x" * (DISCORD_MAX_MESSAGE_LENGTH + 25))

        assert message_id == "message-7"
        assert client.calls[0]["json"] == {"recipient_id": "user-1"}
        assert client.calls[1]["json"] == {"content": "x" * DISCORD_MAX_MESSAGE_LENGTH}

    @pytest.mark.unit
    async def test_raises_when_dm_channel_creation_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-123")
        client = _RecordingAsyncClient([_FakeResponse(403, {"message": "Missing Access"}, text="denied")])

        with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="Discord create DM channel failed \\(HTTP 403\\): Missing Access"):
                await send_discord_dm("user-1", "hello")

    @pytest.mark.unit
    async def test_raises_when_message_send_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-123")
        client = _RecordingAsyncClient(
            [
                _FakeResponse(200, {"id": "channel-9"}),
                _FakeResponse(429, {"message": "Rate limited"}, text="slow down"),
            ]
        )

        with patch("teleclaude.services.discord.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="Discord send message failed \\(HTTP 429\\): Rate limited"):
                await send_discord_dm("user-1", "hello")
