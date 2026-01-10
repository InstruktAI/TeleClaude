"""Terminal adapter for TeleC sessions.

This adapter is a no-op transport that represents local terminal origin
sessions in the adapter graph. It does not send messages itself; UI
adapters handle user-visible output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.core.models import ChannelMetadata, MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import PeerInfo, Session


class TerminalAdapter(BaseAdapter):
    """Minimal adapter representing TeleC/terminal-origin sessions."""

    ADAPTER_KEY = "terminal"

    def __init__(self, client: "AdapterClient") -> None:
        self.client = client

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    async def create_channel(self, session: "Session", title: str, metadata: ChannelMetadata) -> str:
        _ = (session, title, metadata)
        return ""

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        _ = (session, title)
        return True

    async def close_channel(self, session: "Session") -> bool:
        _ = session
        return True

    async def reopen_channel(self, session: "Session") -> bool:
        _ = session
        return True

    async def delete_channel(self, session: "Session") -> bool:
        _ = session
        return True

    async def send_message(self, session: "Session", text: str, *, metadata: MessageMetadata | None = None) -> str:
        _ = (session, text, metadata)
        return ""

    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        _ = (session, message_id, text, metadata)
        return True

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        _ = (session, message_id)
        return True

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        _ = (session, file_path, caption, metadata)
        return ""

    async def discover_peers(self) -> list["PeerInfo"]:
        return []

    async def poll_output_stream(self, session: "Session", timeout: float = 300.0) -> AsyncIterator[str]:
        _ = (session, timeout)

        async def _empty() -> AsyncIterator[str]:
            if False:
                yield ""

        return _empty()
