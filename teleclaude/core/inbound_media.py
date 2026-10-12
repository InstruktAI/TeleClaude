"""Fetching inbound conversation media into a session's own upload directory.

The computer that runs a session fetches the media itself: a file or voice
command forwarded from the computer that received the message carries a
media reference, never a path on that other computer.
"""

from __future__ import annotations

import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.config.machine import config
from teleclaude.config.validation import is_section_available
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import SessionMessageRejectedError, SessionMessageRejectionReason
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.services.whatsapp import fetch_whatsapp_media_bytes
from teleclaude.types.media import MediaProvider, MediaRef

_VOICE_EVENT_TYPES = frozenset({"message.voice", "message.audio"})
_IMAGE_EVENT_TYPE = "message.image"
_IMAGE_MIME_PREFIX = "image/"
_VOICE_SUBDIR = "voice"
_PHOTOS_SUBDIR = "photos"
_FILES_SUBDIR = "files"
_OGG_MIME_TYPE = "audio/ogg"
_OGG_EXTENSION = ".ogg"
_UNKNOWN_EXTENSION = ".bin"
_MIME_PARAMETER_SEPARATOR = ";"
_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
_MEDIA_ID_PREFIX_LENGTH = 12
_FILENAME_TEMPLATE = "{sender}_{timestamp}_{media_id}{extension}"
_UNSUPPORTED_PROVIDER_ERROR = "No media fetch for provider {provider}"
_WHATSAPP_SECTION = "whatsapp"


def is_voice_event(event_type: str) -> bool:
    """Whether a WhatsApp media event carries voice or audio."""
    return event_type in _VOICE_EVENT_TYPES


def _media_subdir(event_type: str, mime_type: str | None) -> str:
    """Choose the destination subdirectory for downloaded media."""
    if is_voice_event(event_type):
        return _VOICE_SUBDIR
    if event_type == _IMAGE_EVENT_TYPE or (mime_type and mime_type.startswith(_IMAGE_MIME_PREFIX)):
        return _PHOTOS_SUBDIR
    return _FILES_SUBDIR


def _media_extension(mime_type: str | None) -> str:
    """Resolve the download extension for a (possibly parameterized) mime type.

    WhatsApp voice notes report ``audio/ogg`` (often with a ``codecs=opus``
    parameter mimetypes.guess_extension does not strip and treats as an
    unknown type) and the bare ``audio/ogg`` reverse lookup is itself
    non-deterministic across Python versions (".oga" vs ".ogg" depending on
    stdlib table order) — pin ".ogg" explicitly rather than relying on it.
    """
    if not mime_type:
        return _UNKNOWN_EXTENSION
    base_mime_type = mime_type.split(_MIME_PARAMETER_SEPARATOR, 1)[0].strip()
    if base_mime_type == _OGG_MIME_TYPE:
        return _OGG_EXTENSION
    return mimetypes.guess_extension(base_mime_type) or _UNKNOWN_EXTENSION


def available_whatsapp_access_token() -> str | None:
    """The WhatsApp access token when WhatsApp is available on this computer, else None."""
    return config.whatsapp.access_token if is_section_available(_WHATSAPP_SECTION, config.whatsapp) else None


async def download_whatsapp_media(
    media_id: str,
    mime_type: str | None,
    sender: str,
    *,
    access_token: str,
    session_id: str,
    event_type: str,
) -> Path:
    """Download inbound WhatsApp media into the session's upload directory and return its path."""
    media_dir = get_session_output_dir(session_id) / _media_subdir(event_type, mime_type)
    media_dir.mkdir(parents=True, exist_ok=True)
    output_path = media_dir / _FILENAME_TEMPLATE.format(
        sender=sender,
        timestamp=datetime.now(UTC).strftime(_TIMESTAMP_FORMAT),
        media_id=media_id[:_MEDIA_ID_PREFIX_LENGTH],
        extension=_media_extension(mime_type),
    )
    output_path.write_bytes(
        await fetch_whatsapp_media_bytes(
            media_id,
            access_token=access_token,
            api_version=config.whatsapp.api_version,
        )
    )
    return output_path


async def fetch_media_ref(media_ref: MediaRef, session_id: str) -> Path:
    """Fetch referenced media into ``session_id``'s upload directory on this computer.

    Media is referenced only when the master forwards it, so a session that is
    gone or closed refuses it before anything is fetched: the refusal fails the
    forwarding request, and the master treats the session as closed (a returning
    customer reopens their desk) instead of counting the media as delivered.
    """
    session = await db.get_session(session_id)
    if session is None:
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.NOT_FOUND)
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.CLOSED)
    whatsapp_access_token = available_whatsapp_access_token()
    if media_ref.provider is MediaProvider.WHATSAPP and whatsapp_access_token is not None:
        return await download_whatsapp_media(
            media_ref.media_id,
            media_ref.mime_type,
            media_ref.sender,
            access_token=whatsapp_access_token,
            session_id=session_id,
            event_type=media_ref.event_type,
        )
    raise ValueError(_UNSUPPORTED_PROVIDER_ERROR.format(provider=media_ref.provider.value))


__all__ = ["available_whatsapp_access_token", "download_whatsapp_media", "fetch_media_ref", "is_voice_event"]
