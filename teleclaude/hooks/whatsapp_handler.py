"""Built-in internal handler for WhatsApp webhook events."""

from __future__ import annotations

import mimetypes
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.agents import get_default_agent
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, SessionMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.types.commands import CreateSessionCommand, HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

logger = get_logger(__name__)


class _WhatsAppSessionMetadata(Protocol):  # pylint: disable=too-few-public-methods
    phone_number: str
    last_received_message_id: str
    last_customer_message_at: str


def _get_whatsapp_metadata(session: object) -> _WhatsAppSessionMetadata | None:
    """Return the WhatsApp UI metadata object for a session, if available."""
    get_metadata = getattr(session, "get_metadata", None)
    if not callable(get_metadata):
        return None
    metadata = get_metadata()
    get_ui = getattr(metadata, "get_ui", None)
    if not callable(get_ui):
        return None
    ui_metadata = get_ui()
    get_whatsapp = getattr(ui_metadata, "get_whatsapp", None)
    if not callable(get_whatsapp):
        return None
    metadata = get_whatsapp()
    return cast(_WhatsAppSessionMetadata, metadata)


def _normalize_phone_number(phone_number: str | None) -> str:
    """Normalize a phone number to digits only."""
    if not phone_number:
        return ""
    return "".join(ch for ch in str(phone_number) if ch.isdigit())


async def _resolve_or_create_session(phone_number: str) -> object | None:
    sessions = await db.get_sessions_by_adapter_metadata("whatsapp", "phone_number", phone_number)
    if sessions:
        return sessions[0]

    create_cmd = CreateSessionCommand(
        project_path=config.computer.help_desk_dir,
        title=f"WhatsApp: {phone_number}",
        origin=InputOrigin.WHATSAPP.value,
        channel_metadata={
            "phone_number": phone_number,
            "platform": "whatsapp",
        },
        session_metadata=SessionMetadata(human_role="customer"),
        auto_command=f"agent {get_default_agent()}",
    )
    result = await get_command_service().create_session(create_cmd)
    session_id_raw = result.get("session_id")
    if not session_id_raw:
        logger.error("WhatsApp session creation returned empty session_id")
        return None
    return await db.get_session(str(session_id_raw))


async def _update_whatsapp_session_metadata(
    session: object,
    *,
    phone_number: str,
    message_id: str,
    timestamp: str,
) -> None:
    metadata = _get_whatsapp_metadata(session)
    if metadata is None:
        return

    metadata.phone_number = phone_number
    metadata.last_received_message_id = message_id
    metadata.last_customer_message_at = timestamp

    try:
        session_id = getattr(session, "session_id", None)
        adapter_metadata = getattr(session, "adapter_metadata", None)
        if not isinstance(session_id, str):
            return
        await db.update_session(session_id, adapter_metadata=adapter_metadata)
    except (AttributeError, TypeError, ValueError):
        logger.debug("Failed to persist WhatsApp metadata for session", exc_info=True)


async def _fetch_whatsapp_media_bytes(media_id: str) -> bytes:
    """Fetch media bytes for a WhatsApp media identifier."""
    headers = {"Authorization": f"Bearer {config.whatsapp.access_token}"}
    media_info_url = f"https://graph.facebook.com/{config.whatsapp.api_version}/{media_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        media_info_response = await client.get(media_info_url, headers=headers)
        media_info_response.raise_for_status()
        media_info = media_info_response.json()
        if not isinstance(media_info, dict) or not media_info.get("url"):
            raise RuntimeError("WhatsApp media lookup missing URL")
        media_url = str(media_info["url"])
        media_response = await client.get(media_url, headers=headers)
        media_response.raise_for_status()
    return media_response.content


def _resolve_media_subdir(event_type: str, mime_type: str | None) -> str:
    """Choose the destination subdirectory for downloaded media."""
    if event_type in {"message.voice", "message.audio"}:
        return "voice"
    if event_type == "message.image" or (mime_type and mime_type.startswith("image/")):
        return "photos"
    return "files"


async def download_whatsapp_media(
    media_id: str,
    mime_type: str | None,
    phone_number: str,
    *,
    session_id: str,
    event_type: str,
) -> Path:
    """Download inbound WhatsApp media into the session workspace and return local path."""
    if not config.whatsapp.access_token:
        raise RuntimeError(
            "WHATSAPP_ACCESS_TOKEN is required to download media",
        )

    media_subdir = _resolve_media_subdir(event_type, mime_type)
    media_dir = get_session_output_dir(session_id) / media_subdir
    media_dir.mkdir(parents=True, exist_ok=True)

    extension = mimetypes.guess_extension(mime_type or "") or ".bin"
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    filename = f"{phone_number}_{timestamp}_{media_id[:12]}{extension}"
    output_path = media_dir / filename
    output_path.write_bytes(await _fetch_whatsapp_media_bytes(media_id))
    return output_path


async def _dispatch_whatsapp_command(
    *,
    session: object,
    message_id: str | None,
    command_name: str,
    payload: dict[str, object],  # guard: loose-dict - Command payload mirrors typed command .to_payload().
    handler: Callable[[], Awaitable[object]],
) -> None:
    command_service = get_command_service()
    client = getattr(command_service, "client", None)
    adapters = getattr(client, "adapters", None)
    if not isinstance(adapters, dict):
        await handler()
        return

    adapter = adapters.get(InputOrigin.WHATSAPP.value)
    if not isinstance(adapter, UiAdapter):
        await handler()
        return

    metadata = MessageMetadata(
        origin=InputOrigin.WHATSAPP.value,
        channel_metadata={"message_id": message_id} if message_id else None,
    )
    dispatch_command = getattr(adapter, "_dispatch_command")
    await dispatch_command(
        session,
        message_id,
        metadata,
        command_name,
        payload,
        handler,
    )  # type: ignore[arg-type]


async def _handle_text_event(
    session: object,
    session_id: str,
    phone_number: str,
    message_id: str,
    event: HookEvent,
) -> None:
    """Dispatch a normalized WhatsApp text event."""
    text = str(event.properties.get("text") or "")
    if not text:
        return
    cmd = ProcessMessageCommand(
        session_id=session_id,
        text=text,
        origin=InputOrigin.WHATSAPP.value,
        actor_id=phone_number,
        actor_name=f"whatsapp:{phone_number}",
    )
    await _dispatch_whatsapp_command(
        session=session,
        message_id=message_id or None,
        command_name="process_message",
        payload=cmd.to_payload(),
        handler=lambda: get_command_service().process_message(cmd),
    )


async def _handle_media_event(
    session: object,
    session_id: str,
    phone_number: str,
    message_id: str,
    event: HookEvent,
) -> None:
    """Dispatch a normalized WhatsApp media event."""
    media_id = str(event.properties.get("media_id") or "")
    if not media_id:
        return
    mime_type = str(event.properties.get("mime_type") or "") or None
    local_path = await download_whatsapp_media(
        media_id,
        mime_type,
        phone_number,
        session_id=session_id,
        event_type=event.type,
    )
    if event.type in {"message.voice", "message.audio"}:
        cmd = HandleVoiceCommand(
            session_id=session_id,
            file_path=str(local_path),
            origin=InputOrigin.WHATSAPP.value,
            message_id=message_id or None,
            actor_id=phone_number,
            actor_name=f"whatsapp:{phone_number}",
        )
        await _dispatch_whatsapp_command(
            session=session,
            message_id=message_id or None,
            command_name="handle_voice",
            payload=cmd.to_payload(),
            handler=lambda: get_command_service().handle_voice(cmd),
        )
        return
    cmd = HandleFileCommand(
        session_id=session_id,
        file_path=str(local_path),
        filename=local_path.name,
        file_size=local_path.stat().st_size,
    )
    await _dispatch_whatsapp_command(
        session=session,
        message_id=message_id or None,
        command_name="handle_file",
        payload=cmd.to_payload(),
        handler=lambda: get_command_service().handle_file(cmd),
    )


async def handle_whatsapp_event(event: HookEvent) -> None:
    """Handle normalized WhatsApp message events."""
    phone_number = _normalize_phone_number(str(event.properties.get("phone_number") or ""))
    if not phone_number:
        logger.warning("WhatsApp event missing phone_number")
        return
    session = await _resolve_or_create_session(phone_number)
    if session is None:
        return
    session_id = str(getattr(session, "session_id", ""))
    if not session_id:
        return
    message_id = str(event.properties.get("message_id") or "")
    await _update_whatsapp_session_metadata(
        session,
        phone_number=phone_number,
        message_id=message_id,
        timestamp=event.timestamp,
    )
    if event.type == "message.text":
        await _handle_text_event(session, session_id, phone_number, message_id, event)
        return
    await _handle_media_event(session, session_id, phone_number, message_id, event)
