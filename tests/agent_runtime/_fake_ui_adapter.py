"""Shared no-op UiAdapter boilerplate for fake adapters in tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo

if TYPE_CHECKING:
    from teleclaude.core.delivery import Destination
    from teleclaude.core.models import Session


class NoOpChannelLifecycleMixin:
    """Trivial channel lifecycle + non-exercised delivery/discovery for fake UiAdapter subclasses."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        del session, title, metadata
        return "channel"

    async def update_channel_title(self, session: Session) -> bool:
        del session
        return True

    async def close_channel(self, session: Session) -> bool:
        del session
        return True

    async def reopen_channel(self, session: Session) -> bool:
        del session
        return True

    async def delete_channel(self, session: Session) -> bool:
        del session
        return True

    async def edit_message(
        self,
        destination: Destination,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        del destination, message_id, text, metadata
        return True

    async def delete_message(self, destination: Destination, message_id: str) -> bool:
        del destination, message_id
        return True

    async def send_file(
        self,
        destination: Destination,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        del destination, file_path, caption, metadata
        return "file"

    async def discover_peers(self) -> list[PeerInfo]:
        return []

    async def poll_output_stream(self, session: Session, timeout: float = 300.0) -> AsyncIterator[str]:
        del session, timeout
        if False:
            yield ""

    def get_ai_session_poll_interval(self) -> float:
        return 1.0
