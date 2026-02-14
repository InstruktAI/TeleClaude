"""Discord adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
from types import ModuleType
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import WORKING_DIR
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class DiscordClientLike(Protocol):
    """Minimal discord.py client surface used by the adapter."""

    user: object | None

    def event(self, coro: Callable[..., Awaitable[None]]) -> object: ...

    async def start(self, token: str) -> None: ...

    async def close(self) -> None: ...


class DiscordAdapter(UiAdapter):
    """Discord bot adapter using discord.py."""

    ADAPTER_KEY = "discord"
    max_message_size = 2000

    def __init__(self, client: "AdapterClient", *, task_registry: "TaskRegistry | None" = None) -> None:
        super().__init__(client)
        self.client = client
        self.task_registry = task_registry
        self._discord: ModuleType = importlib.import_module("discord")
        self._token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        self._guild_id = self._parse_optional_int(os.getenv("DISCORD_GUILD_ID"))
        self._help_desk_channel_id = self._parse_optional_int(os.getenv("DISCORD_HELP_DESK_CHANNEL_ID"))
        self._gateway_task: asyncio.Task[object] | None = None
        self._ready_event = asyncio.Event()
        self._client: DiscordClientLike | None = None

    async def start(self) -> None:
        """Initialize Discord client and start gateway task."""
        if not self._token:
            raise ValueError("DISCORD_BOT_TOKEN is required to start Discord adapter")

        intents = self._discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        self._client = self._discord.Client(intents=intents)
        self._register_gateway_handlers()
        self._ready_event.clear()

        if self.task_registry:
            self._gateway_task = self.task_registry.spawn(self._client.start(self._token), name="discord-gateway")
        else:
            self._gateway_task = asyncio.create_task(self._client.start(self._token), name="discord-gateway")

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=20.0)
        except asyncio.TimeoutError as exc:
            if self._gateway_task and self._gateway_task.done():
                task_exc = self._gateway_task.exception()
                if task_exc:
                    raise RuntimeError(f"Discord gateway failed to start: {task_exc}") from task_exc
            raise RuntimeError("Discord adapter did not become ready within 20 seconds") from exc

    async def stop(self) -> None:
        """Stop Discord client and gateway task."""
        if self._client is not None:
            await self._client.close()
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

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        return None

    def _register_gateway_handlers(self) -> None:
        if self._client is None:
            raise AdapterError("Discord client not initialized")

        async def on_ready() -> None:
            await self._handle_on_ready()

        async def on_message(message: object) -> None:
            await self._handle_on_message(message)

        self._client.event(on_ready)
        self._client.event(on_message)

    async def _handle_on_ready(self) -> None:
        if self._client is None:
            return
        user = getattr(self._client, "user", None)
        logger.info("Discord adapter ready as %s", user)
        self._ready_event.set()

    async def _handle_on_message(self, message: object) -> None:
        if self._is_bot_message(message):
            return

        text = getattr(message, "content", None)
        if not isinstance(text, str) or not text.strip():
            return

        try:
            session = await self._resolve_or_create_session(message)
        except Exception as exc:
            logger.error("Discord session resolution failed: %s", exc, exc_info=True)
            return
        if not session:
            return

        message_id = str(getattr(message, "id", ""))
        channel_metadata = {
            "message_id": message_id,
            "user_id": str(getattr(getattr(message, "author", None), "id", "")),
            "discord_user_id": str(getattr(getattr(message, "author", None), "id", "")),
        }
        metadata = self._metadata(origin=InputOrigin.DISCORD.value, channel_metadata=channel_metadata)
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
        )
        await self._dispatch_command(
            session,
            message_id,
            metadata,
            "process_message",
            cmd.to_payload(),
            lambda: get_command_service().process_message(cmd),
        )

    def _is_bot_message(self, message: object) -> bool:
        author = getattr(message, "author", None)
        if not author:
            return True
        if bool(getattr(author, "bot", False)):
            return True
        if self._client is not None and getattr(self._client, "user", None) is not None:
            self_user_id = getattr(getattr(self._client, "user", None), "id", None)
            if self_user_id is not None and self_user_id == getattr(author, "id", None):
                return True
        return False

    async def _resolve_or_create_session(self, message: object) -> "Session | None":
        user_id = str(getattr(getattr(message, "author", None), "id", ""))
        if not user_id:
            return None

        channel = getattr(message, "channel", None)
        channel_id = self._parse_optional_int(getattr(channel, "id", None))
        guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))
        thread_id = channel_id if self._is_thread_channel(channel) else None

        session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
        if session is None:
            session = await self._create_session_for_message(message, user_id)
            if session is None:
                return None

        return await self._update_session_discord_metadata(
            session,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
        )

    @staticmethod
    def _is_thread_channel(channel: object) -> bool:
        type_name = type(channel).__name__.lower()
        return "thread" in type_name

    async def _find_session(
        self,
        *,
        channel_id: int | None,
        thread_id: int | None,
        user_id: str,
    ) -> "Session | None":
        if thread_id is not None:
            thread_sessions = await db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id)
            if thread_sessions:
                return thread_sessions[0]

        if channel_id is None:
            return None

        channel_sessions = await db.get_sessions_by_adapter_metadata("discord", "channel_id", channel_id)
        for session in channel_sessions:
            if session.get_metadata().get_ui().get_discord().user_id == user_id:
                return session
        return None

    async def _create_session_for_message(self, message: object, user_id: str) -> "Session | None":
        author = getattr(message, "author", None)
        display_name = str(
            getattr(author, "display_name", None) or getattr(author, "name", None) or f"discord-{user_id}"
        )
        create_cmd = CreateSessionCommand(
            project_path=os.path.join(WORKING_DIR, "help-desk"),
            title=f"Discord: {display_name}",
            origin=InputOrigin.DISCORD.value,
            channel_metadata={
                "user_id": user_id,
                "discord_user_id": user_id,
                "human_role": "customer",
                "platform": "discord",
            },
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))
        if not session_id:
            logger.error("Discord session creation returned empty session_id")
            return None
        return await db.get_session(session_id)

    async def _update_session_discord_metadata(
        self,
        session: "Session",
        *,
        user_id: str,
        guild_id: int | None,
        channel_id: int | None,
        thread_id: int | None,
    ) -> "Session":
        discord_meta = session.get_metadata().get_ui().get_discord()
        changed = False

        if discord_meta.user_id != user_id:
            discord_meta.user_id = user_id
            changed = True
        if guild_id is not None and discord_meta.guild_id != guild_id:
            discord_meta.guild_id = guild_id
            changed = True
        if channel_id is not None and discord_meta.channel_id != channel_id:
            discord_meta.channel_id = channel_id
            changed = True
        if thread_id is not None and discord_meta.thread_id != thread_id:
            discord_meta.thread_id = thread_id
            changed = True

        if not changed:
            return session

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return (await db.get_session(session.session_id)) or session
