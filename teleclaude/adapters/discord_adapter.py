"""Discord adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
from collections.abc import Awaitable, Callable, Mapping
from types import ModuleType
from typing import TYPE_CHECKING, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError, ChannelNotProvisionedError
from teleclaude.adapters.discord import (
    AdminReflectionMixin,
    ChannelOperationsMixin,
    GatewayHandlersMixin,
    InfrastructureMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
)
from teleclaude.adapters.discord._runtime import recoverable_operation_errors
from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import discord_policy
from teleclaude.adapters.ui.threaded_output import OverflowContext
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.models import DiscordAdapterMetadata
from teleclaude.utils.markdown import (
    GFM_MARKDOWN_INITIAL_STATE,
    _gfm_closers,
    continuation_prefix_for_gfm_state,
    discordify_markdown,
    scan_gfm_state,
    truncate_gfm_with_consumed,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

DISCORD_TYPING_INTERVAL_S = 5.0


class DiscordClientLike(Protocol):
    """Minimal discord.py client surface used by the adapter."""

    user: object | None

    def event(self, coro: Callable[..., Awaitable[None]]) -> object:
        """Register an event handler."""

    async def start(self, token: str) -> None:
        """Start the client with the given token."""

    async def close(self) -> None:
        """Close the client connection."""


class DiscordAdapter(
    ChannelOperationsMixin,
    GatewayHandlersMixin,
    InfrastructureMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
    AdminReflectionMixin,
    UiAdapter,
):
    """Discord bot adapter using discord.py."""

    ADAPTER_KEY: str = "discord"
    OUTPUT_MESSAGE_ID_FIELD = "id"
    max_message_size = 2000
    _TRUNCATION_SUFFIX = "\n[...truncated...]"

    # -------------------------------------------------------------------------
    # Markdown strategy — GFM
    # -------------------------------------------------------------------------

    def _markdown_initial_state(self) -> object:
        return GFM_MARKDOWN_INITIAL_STATE

    def _continuation_prefix_for_state(self, state: object) -> str:
        return continuation_prefix_for_gfm_state(state)

    def _truncate_for_overflow(self, body_text: str, max_chars: int) -> tuple[str, int]:
        return truncate_gfm_with_consumed(body_text, max_chars=max_chars, suffix="")

    def _scan_markdown_state(self, consumed: str, state: object) -> object:
        return scan_gfm_state(consumed, initial_state=state)

    def _balance_intermediate_chunk(self, text: str) -> str:
        state = scan_gfm_state(text, initial_state=GFM_MARKDOWN_INITIAL_STATE)
        return f"{text}{_gfm_closers(text, state)}"

    def _finalize_overflow_split(
        self,
        active_text: str,
        overflow_context: OverflowContext,
        split_idx: int,
        chunk: str,
    ) -> tuple[int, str]:
        _ = (split_idx, chunk)
        source_limit = max(1, overflow_context.available_for_content - len(overflow_context.continuation_prefix))
        source_chunk = self._pack_complete_lines(active_text, source_limit)[0]
        consumed = len(source_chunk)
        if active_text[consumed : consumed + 1] in {"\n", " "}:
            consumed += 1
        display_chunk = f"{overflow_context.continuation_prefix}{source_chunk}"
        return consumed, self._balance_intermediate_chunk(display_chunk)

    def _convert_markdown_for_platform(self, text: str) -> str:
        """Convert generic markdown into Discord-friendly markdown/text."""
        return discordify_markdown(text)

    # -------------------------------------------------------------------------

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
    # Discord stores output tracking in origin_metadata to prevent cross-adapter races.

    @staticmethod
    def _dc(session: Session) -> DiscordAdapterMetadata:
        """Read Discord section from origin_metadata."""
        return DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))

    def get_action_throttle_interval_s(self, action_kind: str) -> float:
        """Discord typing indicators persist long enough for a coarse pulse cadence."""
        if action_kind == "typing":
            return DISCORD_TYPING_INTERVAL_S
        if action_kind == "title":
            return 600.0
        return super().get_action_throttle_interval_s(action_kind)

    async def send_typing_indicator(self, session: Session) -> None:
        """Send typing indicator to Discord thread."""
        discord_meta = self._dc(session)
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
            recoverable_errors = recoverable_operation_errors(self._discord)
            try:
                await typing_fn()  # type: ignore[unused-ignore]
            except recoverable_errors as exc:
                logger.debug("Typing failed for session %s: %s", session.session_id, exc)
                return
            logger.debug("Typing fired: session=%s thread=%s", session.session_id, discord_meta.thread_id)
        else:
            logger.debug(
                "Typing skipped: typing() not available on channel %s for session %s",
                discord_meta.thread_id,
                session.session_id,
            )

    async def recover_lane_error(
        self,
        session: Session,
        error: Exception,
        task_factory: Callable[[UiAdapter, Session], Awaitable[object]],
        display_title: str,
    ) -> object | None:
        """Absorb expected lane outcomes (unprovisioned channel, stale metadata cleanup)."""
        del task_factory, display_title

        if isinstance(error, ChannelNotProvisionedError):
            logger.info(
                "[DISCORD_RECOVER] Lane skipped — no Discord channel yet for session %s",
                session.session_id,
            )
            return None

        if isinstance(error, AdapterError) and "metadata cleared" in str(error):
            logger.info(
                "[DISCORD_RECOVER] Lane skipped after stale Discord metadata was cleared for session %s: %s",
                session.session_id,
                error,
            )
            return None

        raise error

    async def _send_session_badge(self, session: Session) -> None:
        """No-op — Discord sends thread topper at channel creation."""

    # send_threaded_output: inherited from UiAdapter base class.

    async def on_session_updated(self, session: Session, updated_fields: Mapping[str, object]) -> None:
        """Refresh Discord thread topper when topper-relevant fields change.

        Dispatched by ``AdapterClient.dispatch_session_update`` only for the
        session's origin adapter. Discord owns its own topper-field policy.
        """
        if not {"native_session_id", "active_agent", "thinking_mode"} & set(updated_fields):
            return

        dc = self._dc(session)
        if dc.thread_id is None:
            return

        topper_message_id = dc.thread_topper_message_id
        if not topper_message_id:
            topper_message_id = str(dc.thread_id)
            await db.update_origin_metadata(
                session.session_id, "discord", {"thread_topper_message_id": topper_message_id}
            )

        topper = self._build_thread_topper(session)
        destination = resolve_destination(session, self.ADAPTER_KEY)
        edited = await self.edit_message(destination, topper_message_id, topper)
        if not edited:
            logger.debug(
                "Discord topper refresh failed for session %s (msg=%s)",
                session.session_id,
                topper_message_id,
            )
