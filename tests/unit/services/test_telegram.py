"""Characterization tests for teleclaude.services.telegram."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from teleclaude.services.telegram import (
    DEFAULT_CAPTION_MAX_LENGTH,
    DEFAULT_MESSAGE_MAX_LENGTH,
    send_telegram_dm,
)


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


class TestSendTelegramDm:
    @pytest.mark.unit
    async def test_requires_bot_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="Missing Telegram bot token"):
            await send_telegram_dm("chat-1", "hello")

    @pytest.mark.unit
    async def test_rejects_empty_payload_without_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-123")
        with pytest.raises(ValueError, match="Notification content is empty"):
            await send_telegram_dm("chat-1", "   ")

    @pytest.mark.unit
    async def test_sends_text_message_and_truncates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-123")
        client = _RecordingAsyncClient([_FakeResponse(200, {"ok": True, "result": {"message_id": 42}})])

        with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=client):
            message_id = await send_telegram_dm("chat-1", "x" * (DEFAULT_MESSAGE_MAX_LENGTH + 20))

        assert message_id == "42"
        assert client.calls[0]["url"].endswith("/sendMessage")
        assert client.calls[0]["data"] == {
            "chat_id": "chat-1",
            "text": "x" * DEFAULT_MESSAGE_MAX_LENGTH,
            "disable_web_page_preview": "true",
        }

    @pytest.mark.unit
    async def test_sends_document_with_caption(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-123")
        attachment = tmp_path / "report.txt"
        attachment.write_text("hello", encoding="utf-8")
        client = _RecordingAsyncClient([_FakeResponse(200, {"ok": True, "result": {"message_id": 9}})])

        with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=client):
            message_id = await send_telegram_dm(
                "chat-1",
                "c" * (DEFAULT_CAPTION_MAX_LENGTH + 4),
                file=str(attachment),
            )

        assert message_id == "9"
        assert client.calls[0]["url"].endswith("/sendDocument")
        assert client.calls[0]["data"] == {
            "chat_id": "chat-1",
            "caption": "c" * DEFAULT_CAPTION_MAX_LENGTH,
        }
        files = cast(Mapping[str, object], client.calls[0]["files"])
        document = cast(tuple[str, object], files["document"])
        assert document[0] == "report.txt"

    @pytest.mark.unit
    async def test_raises_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-123")
        client = _RecordingAsyncClient(
            [_FakeResponse(400, {"description": "Bad Request: chat not found"}, text="chat not found")]
        )

        with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="Telegram send failed \\(HTTP 400\\): Bad Request: chat not found"):
                await send_telegram_dm("chat-1", "hello")
