"""Discord adapter for TeleClaude (scaffold)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from types import ModuleType
from typing import TYPE_CHECKING, AsyncIterator

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.ui_adapter import UiAdapter

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class DiscordAdapter(UiAdapter):
    """Discord bot adapter using discord.py.

    This initial scaffold defines lifecycle wiring and adapter surface.
    Gateway handlers and routing are implemented in follow-up tasks.
    """

    ADAPTER_KEY = "discord"
    max_message_size = 2000

    def __init__(self, client: "AdapterClient", *, task_registry: "TaskRegistry | None" = None) -> None:
        super().__init__(client)
        self.client = client
        self.task_registry = task_registry
        self._discord: ModuleType = importlib.import_module("discord")
        self._gateway_task: asyncio.Task[object] | None = None
        self._ready_event = asyncio.Event()
        self._client: object | None = None

    async def start(self) -> None:
        """Initialize Discord client (scaffold)."""
        logger.info("Discord adapter scaffold initialized")

    async def stop(self) -> None:
        """Stop Discord client (scaffold)."""
        if self._gateway_task and not self._gateway_task.done():
            self._gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gateway_task

    async def create_channel(self, session: "Session", title: str, metadata: "ChannelMetadata") -> str:
        _ = (session, title, metadata)
        raise AdapterError("Discord create_channel not implemented yet")

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        _ = (session, title)
        return False

    async def close_channel(self, session: "Session") -> bool:
        _ = session
        return False

    async def reopen_channel(self, session: "Session") -> bool:
        _ = session
        return False

    async def delete_channel(self, session: "Session") -> bool:
        _ = session
        return False

    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: "MessageMetadata | None" = None,
        multi_message: bool = False,
    ) -> str:
        _ = (session, text, metadata, multi_message)
        raise AdapterError("Discord send_message not implemented yet")

    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> bool:
        _ = (session, message_id, text, metadata)
        return False

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        _ = (session, message_id)
        return False

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: "MessageMetadata | None" = None,
    ) -> str:
        _ = (session, file_path, caption, metadata)
        raise AdapterError("Discord send_file not implemented yet")

    async def discover_peers(self) -> list["PeerInfo"]:
        return []

    async def poll_output_stream(  # type: ignore[override,misc]
        self,
        session: "Session",
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        _ = (session, timeout)
        raise NotImplementedError("Discord adapter does not support poll_output_stream")
        yield ""  # pragma: no cover

    def get_max_message_length(self) -> int:
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
        return 0.5
