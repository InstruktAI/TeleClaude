"""Shared no-op UiAdapter boilerplate for fake adapters in tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from teleclaude.core.models import MessageMetadata, PeerInfo

if TYPE_CHECKING:
    from teleclaude.core.delivery import Destination
    from teleclaude.core.models import ChannelMetadata, Session


class NoOpChannelLifecycleMixin:
    """Trivial non-exercised delivery/discovery for fake UiAdapter subclasses.

    Channel lifecycle (create/rename/delete) is Discord-only; fakes composed
    with this mixin carry none of those methods, matching the final
    no-lifecycle UiAdapter shape. Discord-lane fakes use
    DiscordChannelLifecycleMixin instead.
    """

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

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


class DiscordChannelLifecycleMixin:
    """Records channel-lifecycle invocations for Discord-lane preservation assertions.

    Discord is the only adapter that still carries create_channel,
    update_channel_title, and delete_channel post-relocation; the concrete
    fake class initializes the three call-tracking lists this mixin appends to.
    """

    create_channel_calls: list[Session]
    update_channel_title_calls: list[Session]
    delete_channel_calls: list[Session]

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        del title, metadata
        self.create_channel_calls.append(session)
        return "discord-channel"

    async def update_channel_title(self, session: Session) -> bool:
        self.update_channel_title_calls.append(session)
        return True

    async def delete_channel(self, session: Session) -> bool:
        self.delete_channel_calls.append(session)
        return True
