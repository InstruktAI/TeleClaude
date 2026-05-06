"""Characterization tests for teleclaude.hooks.whatsapp_handler."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.models import MessageMetadata
from teleclaude.hooks import whatsapp_handler
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
    """Media download tests for WhatsApp handler."""

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
        monkeypatch.setattr(  # pyright: ignore[reportUnknownLambdaType]
            whatsapp_handler,
            "get_session_output_dir",
            lambda _session_id: tmp_path,
        )
        monkeypatch.setattr(  # pyright: ignore[reportUnknownLambdaType]
            whatsapp_handler.httpx,
            "AsyncClient",
            lambda timeout: client,
        )

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


class TestResolveOrCreateSession:
    """Session resolution and creation tests for WhatsApp handler."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_creates_missing_whatsapp_session_via_api_edge(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolved_session = SimpleNamespace(session_id="session-whatsapp")

        mock_db = SimpleNamespace(
            get_sessions_by_origin_metadata=AsyncMock(return_value=[]),
            get_session=AsyncMock(return_value=resolved_session),
        )
        api = SimpleNamespace(
            connect=AsyncMock(),
            create_session=AsyncMock(return_value=SimpleNamespace(session_id="session-whatsapp")),
            close=AsyncMock(),
        )
        monkeypatch.setattr(whatsapp_handler, "db", mock_db)
        monkeypatch.setattr(
            whatsapp_handler,
            "config",
            SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir="/help-desk")),
        )
        monkeypatch.setattr(whatsapp_handler, "get_default_agent", lambda: "claude")
        monkeypatch.setattr(whatsapp_handler, "TelecAPIClient", lambda: api)

        session = await whatsapp_handler._resolve_or_create_session("15551234567")

        assert session is resolved_session
        api.connect.assert_awaited_once()
        api.create_session.assert_awaited_once_with(
            computer="local",
            project_path="/help-desk",
            agent="claude",
            thinking_mode="slow",
            launch_kind="agent",
            metadata={
                "origin": "whatsapp",
                "origin_metadata": {"phone_number": "15551234567", "platform": "whatsapp"},
            },
        )
        api.close.assert_awaited_once()
        mock_db.get_session.assert_awaited_once_with("session-whatsapp")


class TestHandleWhatsappEvent:
    """Event dispatch tests for WhatsApp handler."""

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
            "actor_id": "whatsapp:15551234567",
            "actor_name": "15551234567",
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
        assert kwargs["payload"]["actor_id"] == "whatsapp:555"

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

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_whatsapp_command_rehydrates_typed_actor_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dispatched: list[tuple[object, str | None, MessageMetadata, str, Mapping[str, object], object]] = []

        class _FakeWhatsappAdapter:
            async def _dispatch_command(self, *args: object, **_kwargs: object) -> None:
                session_arg, message_id, metadata, command_name, payload, handler = args
                assert message_id is None or isinstance(message_id, str)
                assert isinstance(metadata, MessageMetadata)
                assert isinstance(command_name, str)
                assert isinstance(payload, Mapping)
                dispatched.append((session_arg, message_id, metadata, command_name, payload, handler))

        adapter = _FakeWhatsappAdapter()
        command_service = SimpleNamespace(client=SimpleNamespace(adapters={"whatsapp": adapter}))
        monkeypatch.setattr(whatsapp_handler, "UiAdapter", _FakeWhatsappAdapter)
        monkeypatch.setattr(whatsapp_handler, "get_command_service", lambda: command_service)

        await whatsapp_handler._dispatch_whatsapp_command(
            session=SimpleNamespace(session_id="session-4"),
            message_id="wamid-typed",
            command_name="process_message",
            payload={
                "session_id": "session-4",
                "text": "hello",
                "origin": "whatsapp",
                "actor_id": "whatsapp:15551234567",
                "actor_name": "15551234567",
            },
            handler=AsyncMock(),
        )

        assert len(dispatched) == 1
        _, message_id, metadata, command_name, payload, _ = dispatched[0]
        assert message_id == "wamid-typed"
        assert command_name == "process_message"
        assert metadata.origin == "whatsapp"
        assert metadata.platform_message_id == "wamid-typed"
        assert metadata.actor_id == "whatsapp:15551234567"
        assert metadata.actor_name == "15551234567"
        assert payload["actor_id"] == "whatsapp:15551234567"
        assert payload["actor_name"] == "15551234567"
