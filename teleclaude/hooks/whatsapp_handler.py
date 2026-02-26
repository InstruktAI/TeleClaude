"""Built-in internal handler for WhatsApp webhook events."""

from __future__ import annotations

import mimetypes
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.types.commands import CreateSessionCommand, HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

logger = get_logger(__name__)


def _normalize_phone_number(phone_number: str | None) -> str:
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
            "human_role": "customer",
            "platform": "whatsapp",
        },
        auto_command="agent claude",
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
    try:
        metadata = session.get_metadata().get_ui().get_whatsapp()  # type: ignore[attr-defined]
    except Exception:
        return

    metadata.phone_number = phone_number
    metadata.last_received_message_id = message_id
    metadata.last_customer_message_at = timestamp

    try:
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)  # type: ignore[attr-defined]
    except Exception:
        logger.debug("Failed to persist WhatsApp metadata for session", exc_info=True)


async def download_whatsapp_media(media_id: str, mime_type: str | None, phone_number: str) -> Path:
    """Download WhatsApp media to help-desk workspace and return local file path."""
    if not config.whatsapp.access_token:
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN is required to download media")

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

    media_dir = Path(config.computer.help_desk_dir) / "incoming" / "whatsapp"
    media_dir.mkdir(parents=True, exist_ok=True)

    extension = mimetypes.guess_extension(mime_type or "") or ".bin"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"{phone_number}_{timestamp}_{media_id[:12]}{extension}"
    output_path = media_dir / filename
    output_path.write_bytes(media_response.content)
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
    await adapter._dispatch_command(session, message_id, metadata, command_name, payload, handler)  # type: ignore[arg-type]


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
        text = str(event.properties.get("text") or "")
        if text:
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
        return

    media_id = str(event.properties.get("media_id") or "")
    if not media_id:
        return

    mime_type = str(event.properties.get("mime_type") or "") or None
    local_path = await download_whatsapp_media(media_id, mime_type, phone_number)

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
