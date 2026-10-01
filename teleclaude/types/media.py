"""Media a conversation message carries, by reference."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from teleclaude.core.models._types import JsonDict


class MediaProvider(StrEnum):
    """Providers whose inbound media a session's host fetches itself."""

    WHATSAPP = "whatsapp"


class MediaRefField(StrEnum):
    """The keys of a command's nested ``media_ref`` wire block."""

    PROVIDER = "provider"
    MEDIA_ID = "media_id"
    MIME_TYPE = "mime_type"
    SENDER = "sender"
    EVENT_TYPE = "event_type"


@dataclass(frozen=True, kw_only=True)
class MediaRef:
    """Where a session's host fetches inbound media the receiving computer did not store.

    A file or voice command forwarded to another computer carries this instead
    of a local path, which that computer could not read.
    """

    provider: MediaProvider
    media_id: str
    mime_type: str | None = None
    sender: str
    event_type: str

    def to_dict(self) -> JsonDict:
        """Serialize as the nested ``media_ref`` block of a command's wire payload."""
        return {
            MediaRefField.PROVIDER: self.provider.value,
            MediaRefField.MEDIA_ID: self.media_id,
            MediaRefField.MIME_TYPE: self.mime_type,
            MediaRefField.SENDER: self.sender,
            MediaRefField.EVENT_TYPE: self.event_type,
        }

    @staticmethod
    def from_dict(data: Mapping[str, object]) -> MediaRef:
        """Rebuild from the nested ``media_ref`` block of a command's wire payload."""
        mime_type = data.get(MediaRefField.MIME_TYPE)
        return MediaRef(
            provider=MediaProvider(str(data[MediaRefField.PROVIDER])),
            media_id=str(data[MediaRefField.MEDIA_ID]),
            mime_type=mime_type if isinstance(mime_type, str) else None,
            sender=str(data[MediaRefField.SENDER]),
            event_type=str(data[MediaRefField.EVENT_TYPE]),
        )
