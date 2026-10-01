"""Media a conversation message carries, by reference."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from teleclaude.core.models._types import JsonDict


class MediaProvider(str, Enum):
    """Providers whose inbound media a session's host fetches itself."""

    WHATSAPP = "whatsapp"


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
            "provider": self.provider.value,
            "media_id": self.media_id,
            "mime_type": self.mime_type,
            "sender": self.sender,
            "event_type": self.event_type,
        }

    @staticmethod
    def from_dict(data: Mapping[str, object]) -> "MediaRef":
        """Rebuild from the nested ``media_ref`` block of a command's wire payload."""
        mime_type = data.get("mime_type")
        return MediaRef(
            provider=MediaProvider(str(data["provider"])),
            media_id=str(data["media_id"]),
            mime_type=mime_type if isinstance(mime_type, str) else None,
            sender=str(data["sender"]),
            event_type=str(data["event_type"]),
        )
