"""Unit tests for Telegram delivery helpers."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.services.telegram import send_telegram_dm


def _ok_response(message_id: int = 42, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"ok": True, "result": {"message_id": message_id}},
        request=httpx.Request("POST", "https://api.telegram.org/bot/test"),
    )


def _error_response(description: str = "Bad Request", status: int = 400) -> httpx.Response:
    return httpx.Response(
        status,
        json={"ok": False, "description": description},
        request=httpx.Request("POST", "https://api.telegram.org/bot/test"),
    )


def _html_response(status: int = 502) -> httpx.Response:
    return httpx.Response(
        status,
        text="<html>Bad Gateway</html>",
        request=httpx.Request("POST", "https://api.telegram.org/bot/test"),
    )


def _mock_client(response: httpx.Response) -> MagicMock:
    """Create a mock that works as async context manager returning a client with post()."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_send_text_message_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    mock = _mock_client(_ok_response(99))

    with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=mock):
        result = await send_telegram_dm(chat_id="123", content="hello world")
    assert result == "99"


@pytest.mark.asyncio
async def test_send_document_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    doc = tmp_path / "report.txt"
    doc.write_text("report content")

    mock = _mock_client(_ok_response(55))
    with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=mock):
        result = await send_telegram_dm(chat_id="123", content="see attached", file=str(doc))
    assert result == "55"


@pytest.mark.asyncio
async def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Missing Telegram bot token"):
        await send_telegram_dm(chat_id="123", content="hello")


@pytest.mark.asyncio
async def test_empty_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    with pytest.raises(ValueError, match="empty"):
        await send_telegram_dm(chat_id="123", content="")


@pytest.mark.asyncio
async def test_file_not_found_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    with pytest.raises(FileNotFoundError):
        await send_telegram_dm(chat_id="123", content="hi", file="/nonexistent/file.txt")


@pytest.mark.asyncio
async def test_telegram_api_ok_false_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    mock = _mock_client(_error_response("chat not found"))

    with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=mock):
        with pytest.raises(RuntimeError, match="chat not found"):
            await send_telegram_dm(chat_id="123", content="hello")


@pytest.mark.asyncio
async def test_non_json_error_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    mock = _mock_client(_html_response(502))

    with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=mock):
        with pytest.raises(RuntimeError, match="HTTP 502"):
            await send_telegram_dm(chat_id="123", content="hello")


@pytest.mark.asyncio
async def test_non_json_success_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    resp = httpx.Response(
        200,
        text="not json",
        request=httpx.Request("POST", "https://api.telegram.org/bot/test"),
    )
    mock = _mock_client(resp)

    with patch("teleclaude.services.telegram.httpx.AsyncClient", return_value=mock):
        with pytest.raises(RuntimeError, match="non-JSON"):
            await send_telegram_dm(chat_id="123", content="hello")
