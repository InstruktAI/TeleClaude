"""Built-in internal handler for WhatsApp webhook events."""

from __future__ import annotations

import mimetypes
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.inbound import InboundSessionPolicy, resolve_or_create_bound_session
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import (
    AgentDispatchMode,
    MessageMetadata,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.services.whatsapp import fetch_whatsapp_media_bytes
from teleclaude.types.commands import CreateSessionCommand, HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

logger = get_logger(__name__)


def _normalize_phone_number(phone_number: str | None) -> str:
    """Normalize a phone number to digits only."""
    if not phone_number:
        return ""
    return "".join(ch for ch in str(phone_number) if ch.isdigit())


async def _resolve_or_create_session(phone_number: str) -> Session | None:
    async def _find() -> Session | None:
        sessions = await db.get_sessions_by_origin_metadata("whatsapp", "phone_number", phone_number)
        return sessions[0] if sessions else None

    async def _create() -> Session | None:
        cmd = CreateSessionCommand(
            project_path=config.computer.help_desk_dir or "",
            origin=InputOrigin.WHATSAPP.value,
            origin_metadata={"phone_number": phone_number, "platform": "whatsapp"},
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                thinking_mode="slow",
                dispatch_mode=AgentDispatchMode.AUTOMATIC,
            ),
            entry_point=SessionEntryPoint.WHATSAPP,
        )
        result = await get_command_service().create_session(cmd)
        session_id_raw = result.get("session_id")
        if not session_id_raw:
            logger.error("WhatsApp session creation returned empty session_id")
            return None
        return await db.get_session(str(session_id_raw))

    async def _reconcile(session: Session) -> Session:
        return session

    policy = InboundSessionPolicy(find=_find, create=_create, reconcile=_reconcile)
    session, _is_new = await resolve_or_create_bound_session(policy)
    return session


async def _update_whatsapp_session_metadata(
    session: Session,
    *,
    phone_number: str,
    message_id: str,
    timestamp: str,
) -> None:
    await db.update_origin_metadata(
        session.session_id,
        "whatsapp",
        {
            "phone_number": phone_number,
            "last_received_message_id": message_id,
            "last_customer_message_at": timestamp,
        },
    )


def _resolve_media_subdir(event_type: str, mime_type: str | None) -> str:
    """Choose the destination subdirectory for downloaded media."""
    if event_type in {"message.voice", "message.audio"}:
        return "voice"
    if event_type == "message.image" or (mime_type and mime_type.startswith("image/")):
        return "photos"
    return "files"


def _resolve_media_extension(mime_type: str | None) -> str:
    """Resolve the download extension for a (possibly parameterized) mime type.

    WhatsApp voice notes report ``audio/ogg`` (often with a ``codecs=opus``
    parameter mimetypes.guess_extension does not strip and treats as an
    unknown type) and the bare ``audio/ogg`` reverse lookup is itself
    non-deterministic across Python versions (".oga" vs ".ogg" depending on
    stdlib table order) — pin ".ogg" explicitly rather than relying on it.
    """
    if not mime_type:
        return ".bin"
    base_mime_type = mime_type.split(";", 1)[0].strip()
    if base_mime_type == "audio/ogg":
        return ".ogg"
    return mimetypes.guess_extension(base_mime_type) or ".bin"


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

    extension = _resolve_media_extension(mime_type)
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    filename = f"{phone_number}_{timestamp}_{media_id[:12]}{extension}"
    output_path = media_dir / filename
    output_path.write_bytes(
        await fetch_whatsapp_media_bytes(
            media_id,
            access_token=config.whatsapp.access_token,
            api_version=config.whatsapp.api_version,
        )
    )
    return output_path


async def _dispatch_whatsapp_command(
    *,
    session: Session,
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

    payload_actor_id = str(payload.get("actor_id")).strip() if payload.get("actor_id") is not None else None
    payload_actor_name = str(payload.get("actor_name")).strip() if payload.get("actor_name") is not None else None
    payload_actor_avatar_url = (
        str(payload.get("actor_avatar_url")).strip() if payload.get("actor_avatar_url") is not None else None
    )
    metadata = MessageMetadata(
        origin=InputOrigin.WHATSAPP.value,
        platform_message_id=message_id or None,
        actor_id=payload_actor_id or None,
        actor_name=payload_actor_name or None,
        actor_avatar_url=payload_actor_avatar_url or None,
    )
    await adapter.dispatch_command(
        session,
        message_id,
        metadata,
        command_name,
        payload,
        handler,
    )


async def _handle_text_event(
    session: Session,
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
        text_kind=TranscriptEntryKind.ORDINARY,
        source_feature=InjectedTextSourceFeature.WHATSAPP,
        occurrence_key=message_id or None,
        actor_id=f"whatsapp:{phone_number}",
        actor_name=phone_number,
        source_message_id=message_id or None,
    )
    await _dispatch_whatsapp_command(
        session=session,
        message_id=message_id or None,
        command_name="process_message",
        payload=cmd.to_payload(),
        handler=lambda: get_command_service().process_message(cmd),
    )


async def _handle_media_event(
    session: Session,
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
            actor_id=f"whatsapp:{phone_number}",
            actor_name=phone_number,
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
    session_id = session.session_id
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
