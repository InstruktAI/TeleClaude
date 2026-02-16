"""Discord adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
from types import ModuleType
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import WORKING_DIR, config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

if TYPE_CHECKING:
    from datetime import datetime

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
        configured_token = config.discord.token.strip() if config.discord.token else ""
        self._token = configured_token or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        self._guild_id = config.discord.guild_id or self._parse_optional_int(os.getenv("DISCORD_GUILD_ID"))
        self._help_desk_channel_id = config.discord.help_desk_channel_id or self._parse_optional_int(
            os.getenv("DISCORD_HELP_DESK_CHANNEL_ID")
        )
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

    def store_channel_id(self, adapter_metadata: object, channel_id: str) -> None:
        if not isinstance(adapter_metadata, SessionAdapterMetadata):
            return
        parsed = self._parse_optional_int(channel_id)
        if parsed is None:
            return

        discord_meta = adapter_metadata.get_ui().get_discord()
        if self._help_desk_channel_id is not None and parsed != self._help_desk_channel_id:
            discord_meta.thread_id = parsed
            if discord_meta.channel_id is None:
                discord_meta.channel_id = self._help_desk_channel_id
            return

        discord_meta.channel_id = parsed

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        if not callable(fn):
            raise AdapterError(f"{label} is not callable")
        return cast(Callable[..., Awaitable[object]], fn)

    async def create_channel(self, session: "Session", title: str, metadata: "ChannelMetadata") -> str:
        _ = metadata
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        discord_meta = session.get_metadata().get_ui().get_discord()

        if discord_meta.thread_id is not None:
            return str(discord_meta.thread_id)

        if self._help_desk_channel_id is not None:
            forum = await self._get_channel(self._help_desk_channel_id)
            if forum is None:
                raise AdapterError(f"Discord help desk channel {self._help_desk_channel_id} not found")
            if not self._is_forum_channel(forum):
                raise AdapterError(f"Discord channel {self._help_desk_channel_id} is not a Forum Channel")

            thread_id = await self._create_forum_thread(forum, title=title)
            discord_meta.channel_id = self._help_desk_channel_id
            discord_meta.thread_id = thread_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            return str(thread_id)

        if discord_meta.channel_id is not None:
            return str(discord_meta.channel_id)

        raise AdapterError("Discord session has no mapped destination channel")

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_edit_fn = getattr(thread, "edit", None)
        if raw_edit_fn is None:
            return False
        edit_fn = self._require_async_callable(raw_edit_fn, label="Discord thread edit")
        try:
            await edit_fn(name=title)
            return True
        except Exception as exc:
            logger.warning("Failed to rename Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def close_channel(self, session: "Session") -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_edit_fn = getattr(thread, "edit", None)
        if raw_edit_fn is None:
            return False
        edit_fn = self._require_async_callable(raw_edit_fn, label="Discord thread edit")
        try:
            await edit_fn(archived=True, locked=True)
            return True
        except Exception as exc:
            logger.warning("Failed to close Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def reopen_channel(self, session: "Session") -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_edit_fn = getattr(thread, "edit", None)
        if raw_edit_fn is None:
            return False
        edit_fn = self._require_async_callable(raw_edit_fn, label="Discord thread edit")
        try:
            await edit_fn(archived=False, locked=False)
            return True
        except Exception as exc:
            logger.warning("Failed to reopen Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def delete_channel(self, session: "Session") -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_delete_fn = getattr(thread, "delete", None)
        if raw_delete_fn is None:
            return False
        delete_fn = self._require_async_callable(raw_delete_fn, label="Discord thread delete")
        try:
            await delete_fn()
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: "MessageMetadata | None" = None,
        multi_message: bool = False,
    ) -> str:
        _ = multi_message
        destination = await self._resolve_destination_channel(session, metadata=metadata)
        send_fn = self._require_async_callable(getattr(destination, "send", None), label="Discord channel send")
        sent = await send_fn(text)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_message returned message without id")
        return str(message_id)

    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> bool:
        try:
            message = await self._fetch_destination_message(session, message_id, metadata=metadata)
        except AdapterError:
            return False
        edit_fn = self._require_async_callable(getattr(message, "edit", None), label="Discord message edit")
        try:
            await edit_fn(content=text)
            return True
        except Exception as exc:
            logger.warning("Failed to edit Discord message %s: %s", message_id, exc)
            return False

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        try:
            message = await self._fetch_destination_message(session, message_id)
        except AdapterError:
            return False
        delete_fn = self._require_async_callable(getattr(message, "delete", None), label="Discord message delete")
        try:
            await delete_fn()
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord message %s: %s", message_id, exc)
            return False

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: "MessageMetadata | None" = None,
    ) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        destination = await self._resolve_destination_channel(session, metadata=metadata)
        send_fn = self._require_async_callable(getattr(destination, "send", None), label="Discord channel send")
        discord_file = self._discord.File(file_path)
        sent = await send_fn(content=caption, file=discord_file)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_file returned message without id")
        return str(message_id)

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

        # Check if this message is in a relay thread (escalation forum)
        channel = getattr(message, "channel", None)
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id and parent_id == config.discord.escalation_channel_id:
            await self._handle_relay_thread_message(message, text)
            return

        try:
            session = await self._resolve_or_create_session(message)
        except Exception as exc:
            logger.error("Discord session resolution failed: %s", exc, exc_info=True)
            return
        if not session:
            return

        # Relay mode: divert customer messages to the relay thread instead of the AI session
        if session.relay_status == "active" and session.relay_discord_channel_id:
            await self._forward_to_relay_thread(session, text, message)
            return

        message_id = str(getattr(message, "id", ""))
        channel_metadata = {
            "message_id": message_id,
            "user_id": str(getattr(getattr(message, "author", None), "id", "")),
            "discord_user_id": str(getattr(getattr(message, "author", None), "id", "")),
        }
        metadata = self._metadata(channel_metadata=channel_metadata)
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

        channel_id, thread_id = self._extract_channel_ids(message)
        guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))

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

    def _extract_channel_ids(self, message: object) -> tuple[int | None, int | None]:
        channel = getattr(message, "channel", None)
        if not self._is_thread_channel(channel):
            return (self._parse_optional_int(getattr(channel, "id", None)), None)

        thread_id = self._parse_optional_int(getattr(channel, "id", None))
        parent = getattr(channel, "parent", None)
        parent_id = self._parse_optional_int(getattr(parent, "id", None))
        return (parent_id or thread_id, thread_id)

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
            auto_command="agent claude",
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

    async def _resolve_destination_channel(
        self,
        session: "Session",
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> object:
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        metadata_channel_id = (
            self._parse_optional_int(metadata.channel_id) if metadata and metadata.channel_id else None
        )
        discord_meta = session.get_metadata().get_ui().get_discord()
        destination_id = metadata_channel_id or discord_meta.thread_id or discord_meta.channel_id
        if destination_id is None:
            raise AdapterError(f"Session {session.session_id} missing discord channel mapping")

        channel = await self._get_channel(destination_id)
        if channel is None:
            raise AdapterError(f"Discord channel {destination_id} not found")
        return channel

    async def _fetch_destination_message(
        self,
        session: "Session",
        message_id: str,
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> object:
        channel = await self._resolve_destination_channel(session, metadata=metadata)
        fetch_fn = self._require_async_callable(
            getattr(channel, "fetch_message", None), label="Discord channel fetch_message"
        )
        if not message_id.isdigit():
            raise AdapterError(f"Discord message_id must be numeric, got {message_id!r}")
        return await fetch_fn(int(message_id))

    async def _get_channel(self, channel_id: int) -> object | None:
        if self._client is None:
            return None

        get_fn = getattr(self._client, "get_channel", None)
        if callable(get_fn):
            cached = get_fn(channel_id)
            if cached is not None:
                return cached

        fetch_fn = getattr(self._client, "fetch_channel", None)
        if callable(fetch_fn):
            try:
                return await self._require_async_callable(fetch_fn, label="Discord client fetch_channel")(channel_id)
            except Exception as exc:
                logger.debug("Discord fetch_channel(%s) failed: %s", channel_id, exc)
        return None

    async def _create_forum_thread(
        self, forum_channel: object, *, title: str, content: str = "Initializing Help Desk session..."
    ) -> int:
        create_thread_fn = self._require_async_callable(
            getattr(forum_channel, "create_thread", None), label="Discord forum create_thread"
        )

        result = await create_thread_fn(name=title, content=content)
        thread = getattr(result, "thread", None)
        if thread is None and isinstance(result, tuple) and result:
            thread = result[0]
        if thread is None:
            thread = result

        thread_id = self._parse_optional_int(getattr(thread, "id", None))
        if thread_id is None:
            raise AdapterError("Discord create_thread() returned invalid thread id")
        return thread_id

    async def create_escalation_thread(
        self,
        *,
        customer_name: str,
        reason: str,
        context_summary: str | None,
        session_id: str,
    ) -> int:
        """Create a thread in the escalation forum channel for admin relay."""
        escalation_channel_id = config.discord.escalation_channel_id
        if not escalation_channel_id:
            raise AdapterError("escalation_channel_id not configured")

        forum = await self._get_channel(escalation_channel_id)
        if forum is None:
            raise AdapterError(f"Escalation channel {escalation_channel_id} not found")
        if not self._is_forum_channel(forum):
            raise AdapterError(f"Escalation channel {escalation_channel_id} is not a Forum Channel")

        body = f"**Reason:** {reason}"
        if context_summary:
            body += f"\n\n**Context:** {context_summary}"
        body += f"\n\n*Session: {session_id}*"

        return await self._create_forum_thread(forum, title=customer_name, content=body)

    @staticmethod
    def _is_forum_channel(channel: object) -> bool:
        return "forum" in type(channel).__name__.lower()

    # =========================================================================
    # Relay Methods
    # =========================================================================

    async def _forward_to_relay_thread(self, session: "Session", text: str, message: object) -> None:
        """Forward a customer message to the relay Discord thread (relay diversion)."""
        relay_channel_id = session.relay_discord_channel_id
        if not relay_channel_id:
            return
        try:
            thread = await self._get_channel(int(relay_channel_id))
            if thread is None:
                logger.error("Relay thread %s not found", relay_channel_id)
                return

            author = getattr(message, "author", None)
            name = getattr(author, "display_name", None) or "Customer"
            origin = session.last_input_origin or "discord"

            send_fn = self._require_async_callable(getattr(thread, "send", None), label="relay thread send")
            await send_fn(f"**{name}** ({origin}): {text}")
        except Exception:  # noqa: BLE001 - best-effort relay forwarding
            logger.warning("Failed to forward message to relay thread %s", relay_channel_id)

    async def _handle_relay_thread_message(self, message: object, text: str) -> None:
        """Handle an admin message in a relay thread — forward to customer or handback."""
        channel = getattr(message, "channel", None)
        thread_id = str(getattr(channel, "id", ""))

        session = await db.get_session_by_field("relay_discord_channel_id", thread_id)
        if not session:
            return  # Orphaned thread or relay already closed

        if self._is_agent_tag(text):
            await self._handle_agent_handback(session, text, thread_id)
            return

        # Forward admin message to customer via their originating adapter
        author = getattr(message, "author", None)
        admin_name = getattr(author, "display_name", None) or "Admin"
        await self._deliver_to_customer(session, f"{admin_name}: {text}")

    async def _deliver_to_customer(self, session: "Session", text: str) -> None:
        """Deliver a message to the customer via all UI adapters."""
        from teleclaude.core.models import MessageMetadata

        metadata = MessageMetadata()
        try:
            await self.client.send_message(session=session, text=text, metadata=metadata, ephemeral=False)
        except Exception:  # noqa: BLE001 - best-effort delivery
            logger.warning("Failed to deliver relay message to customer session %s", session.session_id[:8])

    def _is_agent_tag(self, text: str) -> bool:
        """Check if a message contains an @agent handback tag."""
        if "@agent" in text.lower():
            return True
        if self._client and getattr(self._client, "user", None):
            bot_id = getattr(getattr(self._client, "user", None), "id", None)
            if bot_id and f"<@{bot_id}>" in text:
                return True
        return False

    async def _handle_agent_handback(self, session: "Session", _text: str, thread_id: str) -> None:
        """Collect relay messages and inject context back into the AI session."""
        messages = await self._collect_relay_messages(thread_id, session.relay_started_at)
        context_block = self._compile_relay_context(messages)

        # Inject context into the AI session's tmux
        from teleclaude.core.tmux_bridge import send_keys_existing_tmux

        await send_keys_existing_tmux(session.tmux_session_name, context_block, send_enter=True)

        # Clear relay state
        await db.update_session(
            session.session_id,
            relay_status=None,
            relay_discord_channel_id=None,
            relay_started_at=None,
        )

        logger.info("Agent handback completed for session %s (thread %s)", session.session_id[:8], thread_id)

    async def _collect_relay_messages(self, thread_id: str, since: "datetime | None") -> list[dict[str, str]]:
        """Read all messages from a relay thread since the given timestamp."""
        thread = await self._get_channel(int(thread_id))
        if not thread:
            return []

        history_fn = getattr(thread, "history", None)
        if not callable(history_fn):
            return []

        messages: list[dict[str, str]] = []
        history_iter = cast(AsyncIterator[object], history_fn(after=since, limit=200))
        async for msg in history_iter:
            if self._is_bot_message(msg):
                continue
            author = getattr(msg, "author", None)
            name = getattr(author, "display_name", None) or "Unknown"
            is_admin = not getattr(author, "bot", False)
            role = "Admin" if is_admin else "Customer"
            messages.append(
                {
                    "role": role,
                    "name": name,
                    "content": getattr(msg, "content", ""),
                }
            )
        return messages

    @staticmethod
    def _sanitize_relay_text(text: str) -> str:
        """Strip control characters and ANSI escape sequences from relay text."""
        import re

        # Remove ANSI escape sequences
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        # Remove other control characters (keep newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text

    @staticmethod
    def _compile_relay_context(messages: list[dict[str, str]]) -> str:
        """Compile relay messages into a context block for AI injection."""
        lines = [
            "[Admin Relay Conversation]",
            "The admin spoke directly with the customer. Here is the full exchange:",
            "",
        ]
        for msg in messages:
            content = DiscordAdapter._sanitize_relay_text(msg["content"])
            lines.append(f"{msg['role']} ({msg['name']}): {content}")

        lines.extend(
            [
                "",
                "The admin has handed the conversation back to you. Continue naturally,",
                "acknowledging what was discussed.",
            ]
        )
        return "\n".join(lines)
