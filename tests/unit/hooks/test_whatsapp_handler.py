"""Characterization tests for teleclaude.hooks.whatsapp_handler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.hooks.whatsapp_handler as whatsapp_handler
from teleclaude.hooks.webhook_models import HookEvent


class _ResponseStub:
    def __init__(self, *, payload: object | None = None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _AsyncClientStub:
    def __init__(self, responses: list[_ResponseStub]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def __aenter__(self) -> _AsyncClientStub:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str]) -> _ResponseStub:
        self.calls.append(("GET", url, headers))
        return self._responses.pop(0)


def _make_event(event_type: str, **properties: str) -> HookEvent:
    return HookEvent(
        source="whatsapp",
        type=event_type,
        timestamp="2025-01-01T00:00:00+00:00",
        properties=properties,
    )


class TestDownloadWhatsappMedia:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_downloads_media_into_the_event_specific_session_subdirectory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        client = _AsyncClientStub(
            [
                _ResponseStub(payload={"url": "https://cdn.example.test/media"}),
                _ResponseStub(content=b"image-bytes"),
            ]
        )
        monkeypatch.setattr(
            whatsapp_handler,
            "config",
            SimpleNamespace(whatsapp=SimpleNamespace(access_token="token", api_version="v21.0")),
        )
        monkeypatch.setattr(whatsapp_handler, "get_session_output_dir", lambda _session_id: tmp_path)
        monkeypatch.setattr(whatsapp_handler.httpx, "AsyncClient", lambda timeout: client)

        output_path = await whatsapp_handler.download_whatsapp_media(
            "media-1234567890abcdef",
            "image/png",
            "15551234567",
            session_id="session-1",
            event_type="message.image",
        )

        assert output_path.parent.name == "photos"
        assert output_path.read_bytes() == b"image-bytes"
        assert output_path.name.endswith(".png")
        assert client.calls[0][1].endswith("/v21.0/media-1234567890abcdef")
        assert client.calls[1][1] == "https://cdn.example.test/media"


class TestHandleWhatsappEvent:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_text_messages_dispatch_process_message_with_normalized_actor_identity(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = SimpleNamespace(session_id="session-1")
        dispatch = AsyncMock()
        monkeypatch.setattr(whatsapp_handler, "_resolve_or_create_session", AsyncMock(return_value=session))
        monkeypatch.setattr(whatsapp_handler, "_update_whatsapp_session_metadata", AsyncMock())
        monkeypatch.setattr(whatsapp_handler, "_dispatch_whatsapp_command", dispatch)

        await whatsapp_handler.handle_whatsapp_event(
            _make_event(
                "message.text",
                phone_number="+1 (555) 123-4567",
                message_id="wamid-1",
                text="hello",
            )
        )

        kwargs = dispatch.await_args.kwargs
        assert kwargs["session"] is session
        assert kwargs["message_id"] == "wamid-1"
        assert kwargs["command_name"] == "process_message"
        assert kwargs["payload"] == {
            "session_id": "session-1",
            "text": "hello",
            "origin": "whatsapp",
            "actor_id": "15551234567",
            "actor_name": "whatsapp:15551234567",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_voice_messages_download_media_and_dispatch_handle_voice(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session = SimpleNamespace(session_id="session-2")
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"voice")
        dispatch = AsyncMock()
        monkeypatch.setattr(whatsapp_handler, "_resolve_or_create_session", AsyncMock(return_value=session))
        monkeypatch.setattr(whatsapp_handler, "_update_whatsapp_session_metadata", AsyncMock())
        monkeypatch.setattr(whatsapp_handler, "download_whatsapp_media", AsyncMock(return_value=audio_path))
        monkeypatch.setattr(whatsapp_handler, "_dispatch_whatsapp_command", dispatch)

        await whatsapp_handler.handle_whatsapp_event(
            _make_event(
                "message.voice",
                phone_number="555",
                message_id="wamid-2",
                media_id="media-voice",
                mime_type="audio/ogg",
            )
        )

        kwargs = dispatch.await_args.kwargs
        assert kwargs["command_name"] == "handle_voice"
        assert kwargs["payload"]["file_path"] == str(audio_path)
        assert kwargs["payload"]["origin"] == "whatsapp"
        assert kwargs["payload"]["actor_id"] == "555"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_voice_media_dispatches_handle_file_with_downloaded_file_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session = SimpleNamespace(session_id="session-3")
        image_path = tmp_path / "photo.png"
        image_path.write_bytes(b"png-bytes")
        dispatch = AsyncMock()
        monkeypatch.setattr(whatsapp_handler, "_resolve_or_create_session", AsyncMock(return_value=session))
        monkeypatch.setattr(whatsapp_handler, "_update_whatsapp_session_metadata", AsyncMock())
        monkeypatch.setattr(whatsapp_handler, "download_whatsapp_media", AsyncMock(return_value=image_path))
        monkeypatch.setattr(whatsapp_handler, "_dispatch_whatsapp_command", dispatch)

        await whatsapp_handler.handle_whatsapp_event(
            _make_event(
                "message.image",
                phone_number="555",
                media_id="media-image",
                mime_type="image/png",
            )
        )

        kwargs = dispatch.await_args.kwargs
        assert kwargs["command_name"] == "handle_file"
        assert kwargs["payload"] == {
            "session_id": "session-3",
            "file_path": str(image_path),
            "filename": "photo.png",
            "file_size": len(b"png-bytes"),
        }
