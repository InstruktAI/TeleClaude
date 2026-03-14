"""Discord adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import TYPE_CHECKING, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord import (
    ChannelOperationsMixin,
    GatewayHandlersMixin,
    InfrastructureMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
    RelayOperationsMixin,
)
from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import discord_policy
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import (
    SessionStatusContext,
    SessionUpdatedContext,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class DiscordClientLike(Protocol):
    """Minimal discord.py client surface used by the adapter."""

    user: object | None

    def event(self, coro: Callable[..., Awaitable[None]]) -> object: ...

    async def start(self, token: str) -> None: ...

    async def close(self) -> None: ...


class DiscordAdapter(  # pyright: ignore[reportIncompatibleMethodOverride,reportIncompatibleVariableOverride]  # type: ignore[misc]
    ChannelOperationsMixin,
    GatewayHandlersMixin,
    InfrastructureMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
    RelayOperationsMixin,
    UiAdapter,
):
    """Discord bot adapter using discord.py."""

    ADAPTER_KEY = "discord"
    THREADED_OUTPUT = True
    max_message_size = 2000
    _TRUNCATION_SUFFIX = "\n[...truncated...]"

    def __init__(self, client: AdapterClient, *, task_registry: TaskRegistry | None = None) -> None:
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
        self._all_sessions_channel_id = config.discord.all_sessions_channel_id or self._parse_optional_int(
            os.getenv("DISCORD_ALL_SESSIONS_CHANNEL_ID")
        )
        self._escalation_channel_id: int | None = config.discord.escalation_channel_id or self._parse_optional_int(
            os.getenv("DISCORD_ESCALATION_CHANNEL_ID")
        )
        self._operator_chat_channel_id: int | None = config.discord.operator_chat_channel_id
        self._announcements_channel_id: int | None = config.discord.announcements_channel_id
        self._general_channel_id: int | None = config.discord.general_channel_id
        self._gateway_task: asyncio.Task[object] | None = None
        self._ready_event = asyncio.Event()
        self._client: DiscordClientLike | None = None
        # project_path -> discord_forum_id mapping, built at startup
        self._project_forum_map: dict[str, int] = {}
        # discord_forum_id -> project_path mapping, built at startup
        self._forum_project_map: dict[int, str] = {}
        # forum-channel-id -> webhook cache for actor-based reflection delivery
        self._reflection_webhook_cache: dict[int, object] = {}
        # team channel ID -> person's home folder path
        self._team_channel_map: dict[int, str] = {}
        self._tree: object | None = None
        self._launcher_registration_view: object | None = None

        # Guard against duplicate infrastructure provisioning on Discord reconnect.
        # on_ready fires on initial connect AND on RESUME failure — re-running
        # provisioning with a stale guild cache creates duplicate categories.
        self._infrastructure_provisioned = False

        # Output QoS scheduler: coalesces stale payloads (coalesce_only mode by default).
        qos_policy = discord_policy(config.discord.qos)
        self._qos_scheduler: OutputQoSScheduler = OutputQoSScheduler(qos_policy)

        # No threaded output buffering — Discord uses the base class
        # edit-in-place model for threaded output delivery.

    async def start(self) -> None:
        """Initialize Discord client and start gateway task."""
        if not self._token:
            raise ValueError("DISCORD_BOT_TOKEN is required to start Discord adapter")

        intents = self._discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        self._client = self._discord.Client(intents=intents)  # pyright: ignore[reportIncompatibleVariableOverride]
        self._register_cancel_slash_command()
        self._register_gateway_handlers()
        self._ready_event.clear()

        if self.task_registry:
            self._gateway_task = self.task_registry.spawn(self._client.start(self._token), name="discord-gateway")
        else:
            self._gateway_task = asyncio.create_task(self._client.start(self._token), name="discord-gateway")

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=20.0)
        except TimeoutError as exc:
            if self._gateway_task and self._gateway_task.done():
                task_exc = self._gateway_task.exception()
                if task_exc:
                    raise RuntimeError(f"Discord gateway failed to start: {task_exc}") from task_exc
            raise RuntimeError("Discord adapter did not become ready within 20 seconds") from exc

        # Start QoS scheduler (no-op if mode == "off").
        self._qos_scheduler.start()

    async def stop(self) -> None:
        """Stop Discord client and gateway task."""
        await self._qos_scheduler.stop()
        self._tree = None
        self._launcher_registration_view = None
        if self._client is not None:
            await self._client.close()
        if self._gateway_task and not self._gateway_task.done():
            self._gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gateway_task

    def _get_enabled_agents(self) -> list[str]:
        return [name for name, agent_cfg in config.agents.items() if agent_cfg.enabled]

    @property
    def _multi_agent(self) -> bool:
        return len(self._get_enabled_agents()) > 1

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        if not callable(fn):
            raise AdapterError(f"{label} is not callable")
        return cast(Callable[..., Awaitable[object]], fn)

    # =========================================================================
    # Per-adapter output message tracking
    # =========================================================================
    # Discord uses adapter_metadata instead of the shared DB column
    # to prevent cross-adapter races with Telegram.

    async def _get_output_message_id(self, session: Session) -> str | None:
        fresh = await db.get_session(session.session_id)
        if fresh:
            return fresh.get_metadata().get_ui().get_discord().output_message_id
        return session.get_metadata().get_ui().get_discord().output_message_id

    async def _store_output_message_id(self, session: Session, message_id: str) -> None:
        meta = session.get_metadata().get_ui().get_discord()
        meta.output_message_id = message_id
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        logger.debug("Stored discord output_message_id: session=%s message_id=%s", session.session_id, message_id)

    async def _clear_output_message_id(self, session: Session) -> None:
        meta = session.get_metadata().get_ui().get_discord()
        meta.output_message_id = None
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        logger.debug("Cleared discord output_message_id: session=%s", session.session_id)

    async def send_typing_indicator(self, session: Session) -> None:
        """Send typing indicator to Discord thread."""
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            logger.debug("Typing skipped: no thread_id for session %s", session.session_id)
            return
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            logger.debug(
                "Typing skipped: channel %s not found for session %s", discord_meta.thread_id, session.session_id
            )
            return
        typing_fn = getattr(thread, "typing", None)
        if typing_fn and callable(typing_fn):
            await typing_fn()  # type: ignore[unused-ignore]
            logger.debug("Typing fired: session=%s thread=%s", session.session_id, discord_meta.thread_id)
        else:
            logger.debug(
                "Typing skipped: typing() not available on channel %s for session %s",
                discord_meta.thread_id,
                session.session_id,
            )

    async def send_output_update(  # type: ignore[override, unused-ignore]  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: Session,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: int | None = None,
        render_markdown: bool = False,
    ) -> str | None:
        """Route Discord output update through the QoS scheduler.

        For threaded sessions: the base class suppresses send_output_update
        (threaded output is delivered via send_threaded_output instead).

        For non-threaded sessions: delegates to QoS scheduler.
        """
        if self.THREADED_OUTPUT:
            return None

        # Non-threaded: existing QoS path.
        if self._qos_scheduler._policy.mode == "off":
            return await UiAdapter.send_output_update(
                self, session, output, started_at, last_output_changed_at, is_final, exit_code, render_markdown
            )

        _self = self
        _session = session
        _output = output
        _started_at = started_at
        _last_changed = last_output_changed_at
        _is_final = is_final
        _exit_code = exit_code
        _render_md = render_markdown

        async def _dispatch() -> str | None:
            return await UiAdapter.send_output_update(
                _self, _session, _output, _started_at, _last_changed, _is_final, _exit_code, _render_md
            )

        self._qos_scheduler.enqueue(session.session_id, _dispatch, is_final=is_final)
        return None  # Delivery is deferred.

    # send_threaded_output: inherited from UiAdapter base class.
    # Discord uses the base class edit-in-place model for threaded output.

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Send or edit the tracked status message in the Discord thread."""
        # Base class fires typing indicator on active/accepted
        await super()._handle_session_status(_event, context)

        session = await db.get_session(context.session_id)
        if not session:
            return
        # Suppress lifecycle badges in threaded mode — only AI output matters.
        if self.THREADED_OUTPUT:
            return
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return  # No Discord thread for this session
        status_text = self._format_lifecycle_status(context.status)
        existing_id = discord_meta.status_message_id
        if existing_id:
            edited = await self.edit_message(session, existing_id, status_text)
            if edited:
                return
            # Edit failed (message deleted?) — clear and fall through to send
            discord_meta.status_message_id = None
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        try:
            new_id = await self.send_message(session, status_text)
            discord_meta.status_message_id = new_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        except Exception as exc:
            logger.debug(
                "Discord status message update failed for session %s: %s",
                context.session_id,
                exc,
            )

    async def _handle_session_updated(self, _event: str, context: SessionUpdatedContext) -> None:
        """Handle generic updates plus Discord topper refresh on native ID binding."""
        await super()._handle_session_updated(_event, context)

        updated_fields = context.updated_fields or {}
        if "native_session_id" not in updated_fields:
            return

        session = await db.get_session(context.session_id)
        if not session or not session.native_session_id:
            return

        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return

        topper_message_id = discord_meta.thread_topper_message_id
        if not topper_message_id:
            topper_message_id = str(discord_meta.thread_id)
            discord_meta.thread_topper_message_id = topper_message_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        topper = self._build_thread_topper(session)
        edited = await self.edit_message(session, topper_message_id, topper)
        if not edited:
            logger.debug(
                "Discord topper refresh failed for session %s (msg=%s)",
                session.session_id,
                topper_message_id,
            )
