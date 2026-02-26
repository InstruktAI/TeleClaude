"""Integration-style tests for WhatsApp normalizer and inbound handler."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.hooks.normalizers.whatsapp import normalize_whatsapp_webhook
from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.hooks.whatsapp_handler import handle_whatsapp_event


def test_normalize_whatsapp_webhook_batches_messages() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "from": "15550001111",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                },
                                {
                                    "id": "wamid.2",
                                    "from": "15550001111",
                                    "timestamp": "1700000001",
                                    "type": "audio",
                                    "audio": {"id": "media-audio-1", "mime_type": "audio/ogg"},
                                },
                            ]
                        }
                    }
                ]
            }
        ]
    }

    events = normalize_whatsapp_webhook(payload, {})

    assert len(events) == 2
    assert events[0].source == "whatsapp"
    assert events[0].type == "message.text"
    assert events[0].properties["message_id"] == "wamid.1"
    assert events[1].type == "message.voice"
    assert events[1].properties["media_id"] == "media-audio-1"


@pytest.mark.asyncio
async def test_handle_whatsapp_event_creates_session_and_processes_text() -> None:
    event = HookEvent.now(
        source="whatsapp",
        type="message.text",
        properties={
            "phone_number": "15550001111",
            "message_id": "wamid.abc",
            "text": "Need help",
        },
        payload={},
    )

    mock_service = SimpleNamespace(
        create_session=AsyncMock(return_value={"session_id": "session-1"}),
        process_message=AsyncMock(),
        handle_file=AsyncMock(),
        handle_voice=AsyncMock(),
    )

    with (
        patch("teleclaude.hooks.whatsapp_handler.get_command_service", return_value=mock_service),
        patch("teleclaude.hooks.whatsapp_handler.db.get_sessions_by_adapter_metadata", new=AsyncMock(return_value=[])),
        patch(
            "teleclaude.hooks.whatsapp_handler.db.get_session",
            new=AsyncMock(
                return_value=SimpleNamespace(session_id="session-1", adapter_metadata=None, get_metadata=lambda: None)
            ),
        ),
        patch("teleclaude.hooks.whatsapp_handler.db.update_session", new=AsyncMock()),
    ):
        await handle_whatsapp_event(event)

    mock_service.create_session.assert_awaited_once()
    mock_service.process_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_whatsapp_event_uses_adapter_dispatch_for_text() -> None:
    event = HookEvent.now(
        source="whatsapp",
        type="message.text",
        properties={
            "phone_number": "15550001111",
            "message_id": "wamid.dispatch",
            "text": "Need dispatch",
        },
        payload={},
    )
    mock_session = SimpleNamespace(
        session_id="session-1",
        adapter_metadata=None,
        lifecycle_status="active",
        get_metadata=lambda: None,
    )
    mock_whatsapp_adapter = AsyncMock(spec=UiAdapter)
    mock_whatsapp_adapter._dispatch_command = AsyncMock()
    mock_service = SimpleNamespace(
        create_session=AsyncMock(return_value={"session_id": "session-1"}),
        process_message=AsyncMock(),
        handle_file=AsyncMock(),
        handle_voice=AsyncMock(),
        client=SimpleNamespace(adapters={"whatsapp": mock_whatsapp_adapter}),
    )

    with (
        patch("teleclaude.hooks.whatsapp_handler.get_command_service", return_value=mock_service),
        patch("teleclaude.hooks.whatsapp_handler.db.get_sessions_by_adapter_metadata", new=AsyncMock(return_value=[])),
        patch("teleclaude.hooks.whatsapp_handler.db.get_session", new=AsyncMock(return_value=mock_session)),
        patch("teleclaude.hooks.whatsapp_handler.db.update_session", new=AsyncMock()),
    ):
        await handle_whatsapp_event(event)

    mock_whatsapp_adapter._dispatch_command.assert_awaited_once()
    mock_service.process_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_whatsapp_event_routes_voice_to_transcription() -> None:
    event = HookEvent.now(
        source="whatsapp",
        type="message.voice",
        properties={
            "phone_number": "15550001111",
            "message_id": "wamid.voice",
            "media_id": "media-voice-1",
            "mime_type": "audio/ogg",
        },
        payload={},
    )

    mock_session = SimpleNamespace(
        session_id="session-voice",
        adapter_metadata=None,
        get_metadata=lambda: None,
    )
    mock_service = SimpleNamespace(
        create_session=AsyncMock(return_value={"session_id": "session-voice"}),
        process_message=AsyncMock(),
        handle_file=AsyncMock(),
        handle_voice=AsyncMock(),
    )

    with TemporaryDirectory() as tmp_dir:
        with (
            patch("teleclaude.hooks.whatsapp_handler.get_command_service", return_value=mock_service),
            patch("teleclaude.hooks.whatsapp_handler.config.computer.help_desk_dir", tmp_dir),
            patch(
                "teleclaude.hooks.whatsapp_handler.db.get_sessions_by_adapter_metadata", new=AsyncMock(return_value=[])
            ),
            patch("teleclaude.hooks.whatsapp_handler.db.get_session", new=AsyncMock(return_value=mock_session)),
            patch("teleclaude.hooks.whatsapp_handler.db.update_session", new=AsyncMock()),
            patch(
                "teleclaude.hooks.whatsapp_handler.download_whatsapp_media",
                new=AsyncMock(return_value=Path(tmp_dir) / "v.ogg"),
            ),
        ):
            await handle_whatsapp_event(event)

    mock_service.handle_voice.assert_awaited_once()
